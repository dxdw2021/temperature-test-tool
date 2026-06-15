#!/usr/bin/python
# -*- coding: UTF-8 -*-
import os
import json
import hmac
import base64
import hashlib
import requests
from time import mktime
from datetime import datetime
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time

class AssembleHeaderException(Exception):
    def __init__(self, msg):
        self.message = msg


class Url:
    def __init__(self, host, path, schema):
        self.host = host
        self.path = path
        self.schema = schema


class universalOcr(object):
    def __init__(self, appid=None, apikey=None, apisecret=None):
        # 如果没有提供参数，尝试从配置文件加载
        if any(param is None for param in [appid, apikey, apisecret]):
            appid, apisecret, apikey = load_config()
            if not all([appid, apisecret, apikey]):
                raise ValueError("API密钥信息不完整，请检查配置文件")
        
        self.appid = appid
        self.apikey = apikey
        self.apisecret = apisecret
        self.url = 'https://api.xf-yun.com/v1/private/hh_ocr_recognize_doc'  # 使用https以提高安全性


    def parse_url(self,requset_url):
        stidx = requset_url.index("://")
        host = requset_url[stidx + 3:]
        schema = requset_url[:stidx + 3]
        edidx = host.index("/")
        if edidx <= 0:
            raise AssembleHeaderException("invalid request url:" + requset_url)
        path = host[edidx:]
        host = host[:edidx]
        u = Url(host, path, schema)
        return u

    def get_body(self, file_path):
        """生成请求体，包含图片数据和配置参数"""
        try:
            with open(file_path, 'rb') as file:
                buf = file.read()
                # 检查文件大小
                if len(buf) > 4 * 1024 * 1024:  # 4MB
                    raise ValueError("图片文件大小超过4MB限制")

            body = {
                "header": {
                    "app_id": self.appid,
                    "status": 3
                },
                "parameter": {
                    "hh_ocr_recognize_doc": {
                        "recognizeDocumentRes": {
                            "encoding": "utf8",
                            "compress": "raw",
                            "format": "json"
                        }
                    }
                },
                "payload": {
                    "image": {
                        "encoding": "jpg",
                        "image": str(base64.b64encode(buf), 'utf-8'),
                        "status": 3
                    }
                }
            }
            return body
        except Exception as e:
            raise ValueError(f"处理图片文件时出错：{str(e)}")


        # print(body)
        return body


# build websocket auth request url
def assemble_ws_auth_url(requset_url, method="POST", api_key="", api_secret=""):
    ocr = universalOcr()
    u = ocr.parse_url(requset_url)
    host = u.host
    path = u.path
    now = datetime.now()
    date = format_date_time(mktime(now.timetuple()))
    # date = "Mon, 22 Aug 2022 03:26:45 GMT"
    signature_origin = "host: {}\ndate: {}\n{} {} HTTP/1.1".format(host, date, method, path)
    signature_sha = hmac.new(api_secret.encode('utf-8'), signature_origin.encode('utf-8'),
                             digestmod=hashlib.sha256).digest()
    signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')
    print("signature:",signature_sha)
    authorization_origin = "api_key=\"%s\", algorithm=\"%s\", headers=\"%s\", signature=\"%s\"" % (
        api_key, "hmac-sha256", "host date request-line", signature_sha)
    authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
    print("authorization:",authorization)
    values = {
        "host": host,
        "date": date,
        "authorization": authorization
    }

    return requset_url + "?" + urlencode(values)



def get_result(ocr_instance, file_path):
    try:
        request_url = assemble_ws_auth_url(ocr_instance.url, "POST", ocr_instance.apikey, ocr_instance.apisecret)
        headers = {'content-type': "application/json", 'host': 'api.xf-yun.com', 'app_id': ocr_instance.appid}
        print("请求URL:", request_url)
        
        body = ocr_instance.get_body(file_path=file_path)
        response = requests.post(request_url, data=json.dumps(body), headers=headers, timeout=30)
        response.raise_for_status()  # 检查HTTP错误
        
        print("响应状态码:", response.status_code)
        re = response.content.decode('utf8')
        str_result = json.loads(re)
        print("\n响应内容:", re)

        if 'header' in str_result:
            if str_result['header']['code'] == 0:
                renew_text = str_result['payload']['recognizeDocumentRes']['text']
                result_json = json.loads(str(base64.b64decode(renew_text), 'utf-8'))
                print("\n识别结果：")
                for line in result_json.get('lines', []):
                    print(line.get('text', ''))
            else:
                print(f"\n识别失败 - 错误码：{str_result['header']['code']}, 错误信息：{str_result['header'].get('message', '未知错误')}")
                print(f"会话ID：{str_result['header'].get('sid', '未知')}")
    except Exception as e:
        print(f"OCR识别过程中出错：{str(e)}")
        raise

def load_config():
    """从配置文件加载API密钥信息"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            api_config = config.get('api', {})
            return (
                api_config.get('appid'),
                api_config.get('apisecret'),
                api_config.get('apikey')
            )
    except Exception as e:
        print(f"读取配置文件失败：{str(e)}")
        return None, None, None

if __name__ == "__main__":
    try:
        # 从配置文件加载API密钥信息
        appid, apisecret, apikey = load_config()
        if not all([appid, apisecret, apikey]):
            raise ValueError("API密钥信息不完整，请检查配置文件")
            
        file_path = "img.png"

        # 检查文件是否存在
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"找不到图片文件：{file_path}")
            
        # 检查文件格式
        allowed_formats = [".jpg", ".jpeg", ".png", ".bmp"]
        if not any(file_path.lower().endswith(fmt) for fmt in allowed_formats):
            raise ValueError(f"不支持的图片格式，请使用以下格式之一：{', '.join(allowed_formats)}")

        ocr = universalOcr()
        get_result(ocr, file_path)
    except FileNotFoundError as e:
        print(f"错误：{str(e)}")
    except ValueError as e:
        print(f"错误：{str(e)}")
    except requests.exceptions.RequestException as e:
        print(f"网络请求错误：{str(e)}")
    except Exception as e:
        print(f"发生未知错误：{str(e)}")
