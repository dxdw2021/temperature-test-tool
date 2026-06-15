# Tesseract-OCR 安装指南

## 下载安装包

1. 访问官方下载页面：<mcurl name="Tesseract-OCR下载页面" url="https://github.com/UB-Mannheim/tesseract/wiki"></mcurl>
2. 根据您的Windows系统版本选择对应的安装包：
   - 64位系统：选择 `tesseract-ocr-w64-setup-xxx.exe`
   - 32位系统：选择 `tesseract-ocr-w32-setup-xxx.exe`
   
   **注意：** 建议下载最新的稳定版本，避免下载带有dev、alpha、beta等标识的测试版本 <mcreference link="https://www.jianshu.com/p/f7cb0b3f337a" index="4">4</mcreference>。

## 安装步骤

1. 运行下载的安装程序
2. 在安装过程中：
   - 选择安装路径（建议使用默认路径）
   - 确保选择了必要的语言包：
     - English（必选）
     - Chinese Simplified（简体中文，推荐）
     <mcreference link="https://blog.csdn.net/qq_40147863/article/details/82285920" index="3">3</mcreference>

## 配置环境变量

1. 打开系统环境变量设置：
   - 方法一：右键点击"此电脑" → 属性 → 高级系统设置 → 环境变量
   - 方法二：按 `Win + R`，输入 `sysdm.cpl`，回车，打开系统属性 → 高级 → 环境变量
   <mcreference link="https://segmentfault.com/a/1190000014086067" index="1">1</mcreference>

2. 在"系统变量"区域：
   - 找到并选择 `Path` 变量
   - 点击"编辑"
   - 点击"新建"
   - 添加Tesseract-OCR的安装路径（例如：`C:\Program Files\Tesseract-OCR`）
   <mcreference link="https://blog.csdn.net/qq_40147863/article/details/82285920" index="3">3</mcreference>

## 验证安装

1. 打开命令提示符（CMD）
2. 输入命令：`tesseract --version`
3. 如果显示版本信息，说明安装和配置成功

## 常见问题

### 1. 提示"tesseract is not installed or it's not in your PATH"

如果在使用Python程序时遇到此错误，可以通过以下方式解决：

1. 确保已正确安装Tesseract-OCR并添加到环境变量
2. 在Python代码中直接指定Tesseract-OCR路径：
   ```python
   import pytesseract
   pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
   ```
   <mcreference link="https://www.jianshu.com/p/f7cb0b3f337a" index="4">4</mcreference>

### 2. 语言包问题

如果需要额外的语言支持：
1. 下载所需的语言包（.traineddata文件）
2. 将文件复制到Tesseract-OCR安装目录下的`tessdata`文件夹中
<mcreference link="https://blog.csdn.net/juzicode00/article/details/121343486" index="5">5</mcreference>

## 参考链接

- [Tesseract-OCR GitHub仓库](https://github.com/tesseract-ocr/tesseract)
- [UB Mannheim Tesseract 安装包](https://github.com/UB-Mannheim/tesseract/wiki)