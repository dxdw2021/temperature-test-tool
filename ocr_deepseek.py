#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""DeepSeek-OCR 接口封装（硅基流动平台）"""

import json
import base64
import requests

API_URL = 'https://api.siliconflow.cn/v1/chat/completions'
MODEL = 'deepseek-ai/DeepSeek-OCR'
MODEL_NEX = 'nex-agi/Nex-N2-Pro'


def load_config():
    """从配置文件加载 SiliconFlow API Key"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config.get('siliconflow', {}).get('api_key', '')
    except Exception as e:
        print(f'读取配置文件失败: {str(e)}')
        return ''


def auto_crop_to_lcd(image_path):
    """自动裁剪图片到 LCD 显示区域（找水平方向的密集纹理条带）"""
    import cv2
    import numpy as np
    
    img = cv2.imread(image_path)
    if img is None:
        return None
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    # 用Sobel边缘检测找密集水平纹理区（7段数码管的特征）
    sobelx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobely = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(sobelx, sobely)
    
    # 每行的平均边缘强度（避开左右边缘以免误判）
    margin = int(w * 0.1)
    row_edge = np.array([mag[y, margin:w-margin].mean() for y in range(h)])
    # 平滑
    kernel = np.ones(5)/5
    smooth = np.convolve(row_edge, kernel, mode='same')
    
    # LCD区域：边缘密度大且亮度高
    row_mean = np.array([gray[y, margin:w-margin].mean() for y in range(h)])
    # 综合评分 = 边缘强度 * 亮度
    score = smooth * row_mean
    
    # 找第一个高评分区域（偏上）
    thresh = np.percentile(score, 90)
    found = None
    start = None
    for y in range(h):
        if score[y] > thresh and start is None:
            start = y
        elif score[y] <= thresh and start is not None:
            if y - start >= 15:
                found = (start, y)
                break
            start = None
    
    if found is None and start is not None and h - start >= 15:
        found = (start, h)
    if found is None:
        print('未找到LCD区域，使用原图', flush=True)
        return None
    
    y1, y2 = found
    y1 = max(0, y1 - 3)
    y2 = min(h, y2 + 3)
    
    # 水平方向：找中心区域内有变化的列
    lcd_strip = gray[y1:y2, :]
    col_std = np.array([lcd_strip[:, c].std() for c in range(w)])
    
    # 限制在中心60%
    cs, ce = int(w*0.2), int(w*0.8)
    cth = np.percentile(col_std[cs:ce], 40)
    cols = np.where(col_std > cth)[0]
    cols_in_center = cols[(cols >= cs) & (cols <= ce)]
    
    if len(cols_in_center) > 0:
        x1 = max(0, cols_in_center[0] - 3)
        x2 = min(w, cols_in_center[-1] + 3)
    else:
        x1, x2 = cs, ce
    
    cropped = img[y1:y2, x1:x2]
    # 确保不小于 28x28（DeepSeek-OCR 要求）
    min_h, min_w = 40, 40
    if cropped.shape[0] < min_h or cropped.shape[1] < min_w:
        # 从原图取相应区域
        y1c = max(0, y1 - (min_h - cropped.shape[0])//2 - 10)
        y2c = min(h, y2 + (min_h - cropped.shape[0])//2 + 10)
        x1c = max(0, x1 - (min_w - cropped.shape[1])//2 - 10)
        x2c = min(w, x2 + (min_w - cropped.shape[1])//2 + 10)
        cropped = img[y1c:y2c, x1c:x2c]
        print(f'  扩展尺寸到: {cropped.shape[0]}x{cropped.shape[1]}', flush=True)
    
    print(f'LCD自动裁剪: {h}x{w} -> {cropped.shape[0]}x{cropped.shape[1]}', flush=True)
    cv2.imwrite(image_path.replace('.png', '_lcd.png'), cropped)
    return cropped


def image_to_base64(image_path, max_size=1024):
    """将图片文件转为 base64 编码，图片超过 max_size 自动缩放"""
    from PIL import Image
    import io
    
    img = Image.open(image_path)
    w, h = img.size
    
    # 如果图片太大，直接缩放到合理尺寸
    if max(w, h) > max_size:
        if w > h:
            new_w = max_size
            new_h = int(h * max_size / w)
        else:
            new_h = max_size
            new_w = int(w * max_size / h)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        print(f'图片已缩放: {w}x{h} -> {new_w}x{new_h}', flush=True)
    
    # 存为 JPEG（更小）
    buf = io.BytesIO()
    img = img.convert('RGB')
    img.save(buf, format='JPEG', quality=85)
    img_data = buf.getvalue()
    
    return base64.b64encode(img_data).decode('utf-8')


def recognize(image_path, api_key=None, model=None):
    """
    使用 DeepSeek-OCR 或 Nex-N2-Pro 识别图片中的文字
    
    Args:
        image_path: 图片文件路径
        api_key: SiliconFlow API Key，None 则从配置文件读取
        model: 模型名，None 则使用默认 deepseek-ai/DeepSeek-OCR
    
    Returns:
        识别到的文本，失败返回 None
    """
    if api_key is None:
        api_key = load_config()
    
    if not api_key:
        raise ValueError('API Key 未配置')
    
    # 图片转 base64（自动缩放+转JPEG）
    img_b64 = image_to_base64(image_path)
    data_url = f'data:image/jpeg;base64,{img_b64}'
    
    model_name = model or MODEL
    print(f'正在请求 {model_name}...', flush=True)
    
    payload = {
        'model': model_name,
        'messages': [
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': data_url
                        }
                    },
                    {
                        'type': 'text',
                        'text': 'This is a binary image of a 7-segment LCD display showing a number. '
                                'The white areas are the lit LCD segments on a black background. '
                                'Read ONLY the digits and decimal point. '
                                'Output ONLY the number, nothing else. '
                                'For example: 25.6 or -5.0 or 100.0'
                    }
                ]
            }
        ]
    }
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    try:
        print(f'正在请求 DeepSeek-OCR (model={MODEL})...', flush=True)
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f'API返回错误: {response.status_code}', flush=True)
            print(f'响应内容: {response.text[:500]}', flush=True)
            
        response.raise_for_status()
        
        result = response.json()
        
        if 'choices' in result and len(result['choices']) > 0:
            text = result['choices'][0]['message']['content']
            print(f'DeepSeek-OCR 识别结果: {text}', flush=True)
            return text.strip()
        else:
            print(f'DeepSeek-OCR 返回异常: {result}', flush=True)
            return None
            
    except requests.exceptions.Timeout:
        print('DeepSeek-OCR 请求超时', flush=True)
        raise
    except requests.exceptions.RequestException as e:
        print(f'DeepSeek-OCR 请求失败: {str(e)}', flush=True)
        raise
    except Exception as e:
        print(f'DeepSeek-OCR 处理出错: {str(e)}', flush=True)
        raise


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        result = recognize(sys.argv[1])
        if result:
            print(f'识别结果: {result}')
        else:
            print('识别失败')
    else:
        print('用法: python ocr_deepseek.py <图片路径>')
