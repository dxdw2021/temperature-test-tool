import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from datetime import datetime, timedelta
import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageGrab, ImageTk
import pandas as pd
import time
import sys
import os
import json
import requests
import threading
import logging

# 日志配置：同时输出到 program.log 和控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('program.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# 将所有 print() 重定向到 logging
_original_print = print
def _print(*args, **kwargs):
    kwargs.pop('flush', None)
    msg = ' '.join(str(a) for a in args)
    if msg:
        logging.info(msg)
print = _print

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

# 默认配置
DEFAULT_BBOX = (140, 172, 513, 1062)  # 默认截图区域

# ADB工具路径
ADB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'adb', 'adb.exe')

# 检查ADB工具是否存在
if not os.path.exists(ADB_PATH):
    print(f'错误: 未找到ADB工具: {ADB_PATH}', flush=True)
    sys.exit(1)

# 将ADB工具路径添加到环境变量
os.environ['PATH'] = os.path.dirname(ADB_PATH) + os.pathsep + os.environ['PATH']

class TemperatureTestApp:
    def __init__(self, root):
        print('初始化应用程序...', flush=True)
        self.root = root
        self.root.title('温度测试工具')
        
        # 设置窗口大小和位置
        window_width = 1280
        window_height = min(900, self.root.winfo_screenheight() - 80)  # 确保窗口高度不超过屏幕
        
        # 计算窗口居中位置
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        # 设置窗口大小和位置
        self.root.geometry(f'{window_width}x{window_height}+{x}+{y}')
        print('设置窗口属性完成', flush=True)
        
        # 设置窗口最小尺寸
        self.root.minsize(1000, 650)
        
        # 创建ADB设备变量
        self.adb_device_var = tk.StringVar()
        
        # 创建界面元素
        self.create_widgets()
        self.root.after(1000, self.redraw_chart_loop)
        print('创建界面元素完成', flush=True)
        
        # 加载配置
        self.config = self.load_config()
        if 'adb_device' in self.config:
            self.adb_device_var.set(self.config['adb_device'])
        if not hasattr(self, 'click_enabled'):
            self.click_enabled = self.config.get('click_enabled', False)
        if not hasattr(self, 'click_steps'):
            self.click_steps = self.config.get('click_steps', [])
        self.bind_config_events()
        print('配置加载完成', flush=True)
        
        # 检查Tesseract是否安装
        self.check_tesseract()
        print('Tesseract检查完成', flush=True)

        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

        # 绑定窗口大小变化事件
        self.root.bind('<Configure>', self.on_window_resize)
        print('初始化完成', flush=True)

    def on_window_resize(self, event):
        """处理窗口大小变化事件"""
        # 仅处理主窗口的大小变化
        if event.widget == self.root:
            # 如果有最后一次截图和处理后的图像，只更新显示
            if hasattr(self, 'last_screenshot') and hasattr(self, 'last_processed'):
                try:
                    # 直接更新预览，不重新处理图像
                    self.update_image_preview(self.last_screenshot, self.last_processed)
                except Exception as e:
                    print(f'调整图像大小失败: {str(e)}')
            if hasattr(self, 'config'):
                if hasattr(self, 'geometry_save_after'):
                    self.root.after_cancel(self.geometry_save_after)
                self.geometry_save_after = self.root.after(500, self.save_window_config)

    def save_window_config(self):
        """保存窗口尺寸配置"""
        self.config['window_width'] = self.root.winfo_width()
        self.config['window_height'] = self.root.winfo_height()
        self.save_config()

    def create_widgets(self):
        """创建界面元素"""
        self.main_frame = tb.Frame(self.root, padding='5')
        self.main_frame.pack(fill=BOTH, expand=YES)

        self.notebook = tb.Notebook(self.main_frame, padding=8)
        self.notebook.pack(fill=BOTH, expand=YES)
        self.test_frame = tb.Frame(self.notebook)
        self.chart_frame = tb.Frame(self.notebook)
        self.notebook.add(self.test_frame, text='测试')
        self.notebook.add(self.chart_frame, text='温度曲线')
        self.notebook.bind('<<NotebookTabChanged>>', self.on_notebook_tab_changed)
        self.chart_data = []
        self.create_chart_widgets()

        # 滚动容器：Canvas + Scrollbar 包裹测试页所有内容
        self.test_canvas = tk.Canvas(self.test_frame, highlightthickness=0)
        self.test_scrollbar = tb.Scrollbar(self.test_frame, orient=VERTICAL, command=self.test_canvas.yview)
        self.test_scroll_frame = tb.Frame(self.test_canvas)
        self.test_scroll_frame.bind('<Configure>',
            lambda e: self.test_canvas.configure(scrollregion=self.test_canvas.bbox('all')))
        self.test_canvas.create_window((0, 0), window=self.test_scroll_frame, anchor='nw', tags='inner')
        self.test_canvas.configure(yscrollcommand=self.test_scrollbar.set)
        # 让内框架宽度跟随画布宽度
        def _resize_inner(event):
            self.test_canvas.itemconfig('inner', width=event.width)
        self.test_canvas.bind('<Configure>', _resize_inner)

        self.test_canvas.pack(side=LEFT, fill=BOTH, expand=YES)
        self.test_scrollbar.pack(side=RIGHT, fill=Y)

        # 鼠标滚轮滚动（跨平台）
        def _on_mousewheel(event):
            self.test_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        def _bind_wheel(event):
            self.test_canvas.bind_all('<MouseWheel>', _on_mousewheel)
        def _unbind_wheel(event):
            self.test_canvas.unbind_all('<MouseWheel>')
        self.test_canvas.bind('<Enter>', _bind_wheel)
        self.test_canvas.bind('<Leave>', _unbind_wheel)

        # 所有子控件创建到 test_scroll_frame
        sf = self.test_scroll_frame

        # 顶部按钮区域
        self.top_buttons_frame = tb.Frame(sf)
        self.top_buttons_frame.pack(anchor=NW, pady=(0, 4))

        self.config_btn = tb.Button(self.top_buttons_frame, text='设置截图区域', command=self.configure_bbox)
        self.config_btn.pack(side=LEFT, padx=(0, 4))

        self.open_folder_btn = tb.Button(self.top_buttons_frame, text='打开图片文件夹', command=self.open_image_folder)
        self.open_folder_btn.pack(side=LEFT, padx=4)

        self.export_btn = tb.Button(self.top_buttons_frame, text='导出数据', command=self.export_data, style='success.TButton')
        self.export_btn.pack(side=LEFT, padx=4)

        # 温度显示区域
        self.temp_frame = tb.LabelFrame(sf, text='当前温度')
        self.temp_frame.pack(fill=X, pady=(0, 4))

        self.temp_label = tb.Label(self.temp_frame, text='--°C', font=('Arial', 24))
        self.temp_label.pack(pady=4)

        # 图像显示区域
        self.image_frame = tb.LabelFrame(sf, text='图像预览')
        self.image_frame.pack(fill=BOTH, expand=YES, pady=(0, 4))
        self.image_frame.grid_rowconfigure(0, weight=1)
        self.image_frame.grid_columnconfigure(0, weight=1)

        self.image_panes = tb.Panedwindow(self.image_frame, orient=HORIZONTAL)
        self.image_panes.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        self.original_frame = tb.LabelFrame(self.image_panes, text='原始截图')
        self.original_frame.grid_rowconfigure(0, weight=1)
        self.original_frame.grid_columnconfigure(0, weight=1)
        self.original_label = tb.Label(self.original_frame, anchor='center')
        self.original_label.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        self.processed_frame = tb.LabelFrame(self.image_panes, text='处理后图像')
        self.processed_frame.grid_rowconfigure(0, weight=1)
        self.processed_frame.grid_columnconfigure(0, weight=1)
        self.processed_label = tb.Label(self.processed_frame, anchor='center')
        self.processed_label.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        self.image_panes.add(self.original_frame, weight=1)
        self.image_panes.add(self.processed_frame, weight=1)

        # ── 测试参数设置区域（4列布局） ──
        self.settings_frame = tb.LabelFrame(sf, text='测试参数设置')
        self.settings_frame.pack(fill=X, pady=(0, 4))

        # Row 0: 截图方式 + 识别方式
        tb.Label(self.settings_frame, text='截图方式:').grid(row=0, column=0, padx=5, pady=2, sticky=E)
        self.capture_mode_var = tk.StringVar(value='screen')
        self.capture_mode_combo = tb.Combobox(self.settings_frame, textvariable=self.capture_mode_var,
                                              values=['screen', 'adb'], width=12, state='readonly')
        self.capture_mode_combo.grid(row=0, column=1, padx=5, pady=2, sticky=W)

        tb.Label(self.settings_frame, text='识别方式:').grid(row=0, column=2, padx=5, pady=2, sticky=E)
        self.ocr_mode_var = tk.StringVar(value='本地OCR(Tesseract)')
        self.ocr_mode_combo = tb.Combobox(self.settings_frame, textvariable=self.ocr_mode_var,
                                           values=['本地OCR(Tesseract)', 'API识别(硅基)'], width=18, state='readonly')
        self.ocr_mode_combo.grid(row=0, column=3, padx=5, pady=2, sticky=W)

        # Row 1: 截图间隔 + 测试时长
        tb.Label(self.settings_frame, text='截图间隔(秒):').grid(row=1, column=0, padx=5, pady=2, sticky=E)
        self.interval_var = tk.StringVar(value='5')
        self.interval_entry = tb.Entry(self.settings_frame, textvariable=self.interval_var, width=12)
        self.interval_entry.grid(row=1, column=1, padx=5, pady=2, sticky=W)

        tb.Label(self.settings_frame, text='测试时长(分钟):').grid(row=1, column=2, padx=5, pady=2, sticky=E)
        self.duration_var = tk.StringVar(value='60')
        self.duration_entry = tb.Entry(self.settings_frame, textvariable=self.duration_var, width=12)
        self.duration_entry.grid(row=1, column=3, padx=5, pady=2, sticky=W)

        # Row 2: 缩放因子 + CLAHE
        tb.Label(self.settings_frame, text='缩放因子:').grid(row=2, column=0, padx=5, pady=2, sticky=E)
        self.scale_var = tk.StringVar(value='7')
        self.scale_entry = tb.Entry(self.settings_frame, textvariable=self.scale_var, width=12)
        self.scale_entry.grid(row=2, column=1, padx=5, pady=2, sticky=W)

        tb.Label(self.settings_frame, text='CLAHE clipLimit:').grid(row=2, column=2, padx=5, pady=2, sticky=E)
        self.clip_var = tk.StringVar(value='3.0')
        self.clip_entry = tb.Entry(self.settings_frame, textvariable=self.clip_var, width=12)
        self.clip_entry.grid(row=2, column=3, padx=5, pady=2, sticky=W)

        # Row 3: alpha + beta
        tb.Label(self.settings_frame, text='对比度 alpha:').grid(row=3, column=0, padx=5, pady=2, sticky=E)
        self.alpha_var = tk.StringVar(value='3.0')
        self.alpha_entry = tb.Entry(self.settings_frame, textvariable=self.alpha_var, width=12)
        self.alpha_entry.grid(row=3, column=1, padx=5, pady=2, sticky=W)

        tb.Label(self.settings_frame, text='对比度 beta:').grid(row=3, column=2, padx=5, pady=2, sticky=E)
        self.beta_var = tk.StringVar(value='5')
        self.beta_entry = tb.Entry(self.settings_frame, textvariable=self.beta_var, width=12)
        self.beta_entry.grid(row=3, column=3, padx=5, pady=2, sticky=W)

        # Row 4: 反色值 + 去低色阈值
        tb.Label(self.settings_frame, text='反色值:').grid(row=4, column=0, padx=5, pady=2, sticky=E)
        self.invert_var = tk.BooleanVar(value=False)
        self.invert_check = tb.Checkbutton(self.settings_frame, text='启用', variable=self.invert_var)
        self.invert_check.grid(row=4, column=1, padx=5, pady=2, sticky=W)

        tb.Label(self.settings_frame, text='去低色阈值:').grid(row=4, column=2, padx=5, pady=2, sticky=E)
        self.threshold_var = tk.StringVar(value='30')
        self.threshold_entry = tb.Entry(self.settings_frame, textvariable=self.threshold_var, width=12)
        self.threshold_entry.grid(row=4, column=3, padx=5, pady=2, sticky=W)

        # Row 5: 保存路径
        tb.Label(self.settings_frame, text='保存路径:').grid(row=5, column=0, padx=5, pady=2, sticky=E)
        self.save_path_var = tk.StringVar(value='.')
        self.save_path_entry = tb.Entry(self.settings_frame, textvariable=self.save_path_var, width=18)
        self.save_path_entry.grid(row=5, column=1, columnspan=2, padx=5, pady=2, sticky=EW)
        tb.Button(self.settings_frame, text='浏览', command=self._browse_save_path, style='secondary.TButton').grid(row=5, column=3, padx=5, pady=2, sticky=W)

        # Row 6: 应用参数按钮
        self.apply_btn = tb.Button(self.settings_frame, text='应用参数', command=self.apply_image_params)
        self.apply_btn.grid(row=6, column=0, columnspan=4, pady=(4, 2))

        # ── 控制区域（分 3 行：测试控制 / ADB 配置 / API 配置） ──
        self.control_frame = tb.Frame(sf)
        self.control_frame.pack(fill=X, pady=(0, 4))

        # 行 1：测试控制
        test_ctrl = tb.Frame(self.control_frame)
        test_ctrl.pack(fill=X, pady=(0, 4))

        self.start_btn = tb.Button(test_ctrl, text='开始测试', command=self.start_test, style='success.TButton')
        self.start_btn.pack(side=LEFT, padx=(0, 4))

        self.stop_btn = tb.Button(test_ctrl, text='停止测试', command=self.stop_test, style='danger.TButton', state=DISABLED)
        self.stop_btn.pack(side=LEFT, padx=4)

        self.progress_label = tb.Label(test_ctrl, text='')
        self.progress_label.pack(side=LEFT, padx=10)

        # 行 2：ADB 设备配置
        self.adb_frame = tb.LabelFrame(self.control_frame, text='ADB 设备配置')
        self.adb_frame.pack(fill=X, pady=(0, 4))

        adb_inner = tb.Frame(self.adb_frame)
        adb_inner.pack(fill=X, padx=5, pady=4)

        tb.Label(adb_inner, text='设备地址:').pack(side=LEFT)
        self.adb_device_var = tk.StringVar(value='188.188.22.217:5555')
        self.adb_entry = tb.Entry(adb_inner, textvariable=self.adb_device_var, width=20)
        self.adb_entry.pack(side=LEFT, padx=(4, 8))

        self.wifi_connect_btn = tb.Button(adb_inner, text='WIFI连接', command=self.connect_wifi_device, style='info.TButton')
        self.wifi_connect_btn.pack(side=LEFT, padx=2)

        self.usb_connect_btn = tb.Button(adb_inner, text='USB连接', command=self.connect_usb_device, style='info.TButton')
        self.usb_connect_btn.pack(side=LEFT, padx=2)

        # 行 3：API 识别配置
        api_frame = tb.LabelFrame(self.control_frame, text='API 识别配置')
        api_frame.pack(fill=X, pady=(0, 4))

        api_inner = tb.Frame(api_frame)
        api_inner.pack(fill=X, padx=5, pady=4)

        tb.Label(api_inner, text='提供商:').pack(side=LEFT)
        self.api_provider_var = tk.StringVar(value='DeepSeek-OCR')
        self.api_provider_combo = tb.Combobox(api_inner, textvariable=self.api_provider_var,
                                               values=['讯飞', 'DeepSeek-OCR'], width=12, state='readonly')
        self.api_provider_combo.pack(side=LEFT, padx=(4, 8))

        tb.Label(api_inner, text='模型:').pack(side=LEFT)
        self.sf_model_var = tk.StringVar(value='deepseek-ai/DeepSeek-OCR')
        self.sf_model_combo = tb.Combobox(api_inner, textvariable=self.sf_model_var,
                                           values=['deepseek-ai/DeepSeek-OCR', 'nex-agi/Nex-N2-Pro'],
                                           width=24, state='readonly')
        self.sf_model_combo.pack(side=LEFT, padx=(4, 8))

        tb.Label(api_inner, text='Key:').pack(side=LEFT)
        self.sf_api_key_var = tk.StringVar()
        self.sf_api_key_entry = tb.Entry(api_inner, textvariable=self.sf_api_key_var, width=28, show='*')
        self.sf_api_key_entry.pack(side=LEFT, padx=(4, 8))

        self.api_btn = tb.Button(api_inner, text='API识别', command=self.api_recognize, style='info.TButton')
        self.api_btn.pack(side=LEFT, padx=2)

        self.train_font_btn = tb.Button(api_inner, text='字库训练', command=self.start_font_training, style='secondary.TButton')
        self.train_font_btn.pack(side=LEFT, padx=2)

        # ── 数据显示区域 ──
        self.data_frame = tb.LabelFrame(sf, text='测试数据')
        self.data_frame.pack(fill=BOTH, expand=YES, pady=(0, 4))

        columns = ('时间', '温度值')
        self.tree = tb.Treeview(self.data_frame, columns=columns, show='headings')
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=180 if col == '时间' else 100)

        self.scrollbar = tb.Scrollbar(self.data_frame, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        self.tree.pack(side=LEFT, fill=BOTH, expand=YES)
        self.scrollbar.pack(side=RIGHT, fill=Y)

        # 测试状态变量
        self.is_testing = False
        self.test_data = []

    def create_chart_widgets(self):
        """创建温度曲线标签页"""
        toolbar = tb.Frame(self.chart_frame)
        toolbar.pack(fill=X, padx=5, pady=5)

        tb.Label(toolbar, text='最近 1 小时温度曲线', font=('Arial', 11, 'bold')).pack(side=LEFT)
        self.chart_summary_label = tb.Label(toolbar, text='等待识别数据...')
        self.chart_summary_label.pack(side=LEFT, padx=10)
        tb.Button(toolbar, text='清空曲线', command=self.clear_chart_data, style='secondary.TButton').pack(side=RIGHT)

        self.chart_canvas = tk.Canvas(self.chart_frame, background='white', highlightthickness=1, highlightbackground='#d0d0d0')
        self.chart_canvas.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        self.chart_canvas.bind('<Configure>', lambda event: self.draw_chart())

    def bind_config_events(self):
        """绑定配置控件，确保关闭窗口前持久化"""
        config_widgets = [
            self.capture_mode_combo,
            self.adb_entry,
            self.ocr_mode_combo,
            self.interval_entry,
            self.duration_entry,
            self.scale_entry,
            self.clip_entry,
            self.alpha_entry,
            self.beta_entry,
            self.threshold_entry,
            self.save_path_entry,
            self.api_provider_combo,
            self.sf_model_combo,
            self.sf_api_key_entry
        ]

        for widget in config_widgets:
            widget.bind('<<ComboboxSelected>>', lambda event: self.save_config())
            widget.bind('<FocusOut>', lambda event: self.save_config())
            widget.bind('<Return>', lambda event: self.save_config())

    def on_close(self):
        """关闭窗口前保存配置"""
        self.is_testing = False
        self.save_window_config()
        self.root.destroy()

    def on_notebook_tab_changed(self, event=None):
        """切换到温度曲线标签页时刷新曲线"""
        if self.notebook.tab(self.notebook.select(), 'text') == '温度曲线':
            self.draw_chart()
        self.save_config()

    def redraw_chart_loop(self):
        """定时刷新曲线时间轴"""
        if hasattr(self, 'chart_data') and self.chart_data:
            self.draw_chart()
        self.root.after(1000, self.redraw_chart_loop)

    def clear_chart_data(self):
        """清空曲线数据"""
        self.chart_data.clear()
        self.draw_chart()

    def add_chart_data(self, timestamp, temp):
        """添加并绘制曲线数据"""
        self.chart_data.append((timestamp, temp))
        cutoff = datetime.now() - timedelta(hours=2)
        self.chart_data = [(ts, value) for ts, value in self.chart_data if ts >= cutoff]
        self.draw_chart()

    def draw_chart(self):
        """绘制最近 1 小时温度曲线"""
        if not hasattr(self, 'chart_canvas'):
            return

        self.chart_canvas.delete('all')
        width = self.chart_canvas.winfo_width()
        height = self.chart_canvas.winfo_height()
        if width < 200 or height < 150:
            return

        margin_left = 65
        margin_right = 25
        margin_top = 30
        margin_bottom = 50
        plot_width = width - margin_left - margin_right
        plot_height = height - margin_top - margin_bottom

        now = datetime.now()
        cutoff = now - timedelta(hours=1)
        data = [(ts, temp) for ts, temp in self.chart_data if ts >= cutoff]

        # 绘制图表背景
        self.chart_canvas.create_rectangle(
            margin_left, margin_top,
            margin_left + plot_width, margin_top + plot_height,
            outline='#e0e0e0', fill='#fafbfc'
        )

        if not data:
            self.chart_canvas.create_text(
                width / 2, height / 2,
                text='暂无最近 1 小时温度数据',
                fill='#999999', font=('Microsoft YaHei', 11)
            )
            if hasattr(self, 'chart_summary_label'):
                self.chart_summary_label.configure(text='暂无最近 1 小时数据')
            return

        temps = [temp for _, temp in data]
        min_temp = min(temps)
        max_temp = max(temps)
        padding = max((max_temp - min_temp) * 0.15, 0.5)
        min_temp -= padding
        max_temp += padding
        if max_temp - min_temp < 1:
            max_temp = min_temp + 1

        # 绘制水平网格线和 Y 轴标签
        for i in range(5):
            ratio = i / 4
            value = min_temp + (max_temp - min_temp) * ratio
            y = margin_top + plot_height - ratio * plot_height
            self.chart_canvas.create_line(
                margin_left, y, margin_left + plot_width, y,
                fill='#eeeeee', dash=(2, 4)
            )
            self.chart_canvas.create_text(
                margin_left - 8, y,
                text=f'{value:.1f}', anchor=E,
                fill='#666666', font=('Consolas', 9)
            )

        # 绘制 X 轴时间标签（每 10 分钟一个刻度）
        for i in range(7):
            ratio = i / 6
            time_label = cutoff + timedelta(minutes=10 * i)
            x = margin_left + ratio * plot_width
            self.chart_canvas.create_line(
                x, margin_top + plot_height,
                x, margin_top + plot_height + 5,
                fill='#cccccc'
            )
            self.chart_canvas.create_text(
                x, margin_top + plot_height + 18,
                text=time_label.strftime('%H:%M'),
                anchor=N, fill='#666666', font=('Consolas', 8)
            )

        # 绘制坐标轴
        self.chart_canvas.create_line(
            margin_left, margin_top, margin_left, margin_top + plot_height,
            fill='#aaaaaa', width=1
        )
        self.chart_canvas.create_line(
            margin_left, margin_top + plot_height,
            margin_left + plot_width, margin_top + plot_height,
            fill='#aaaaaa', width=1
        )

        # 轴标题
        self.chart_canvas.create_text(
            margin_left - 45, margin_top + plot_height / 2,
            text='°C', anchor=E, fill='#888888',
            font=('Microsoft YaHei', 9)
        )
        self.chart_canvas.create_text(
            margin_left + plot_width / 2, margin_top + plot_height + 40,
            text='时间', anchor=N, fill='#888888',
            font=('Microsoft YaHei', 9)
        )

        # 计算数据点坐标
        points = []
        for ts, temp in data:
            x_ratio = (ts - cutoff).total_seconds() / 3600
            x = margin_left + x_ratio * plot_width
            y_ratio = (max_temp - temp) / (max_temp - min_temp)
            y = margin_top + y_ratio * plot_height
            points.append((x, y))

        # 绘制填充区域（渐变效果模拟）
        if len(points) > 1:
            fill_points = list(points)
            fill_points.append((points[-1][0], margin_top + plot_height))
            fill_points.append((points[0][0], margin_top + plot_height))
            self.chart_canvas.create_polygon(
                fill_points, fill='#e8f0fe', outline=''
            )

        # 绘制数据线
        if len(points) == 1:
            x, y = points[0]
            self.chart_canvas.create_oval(
                x - 5, y - 5, x + 5, y + 5,
                fill='#1a73e8', outline='#1a73e8'
            )
        else:
            self.chart_canvas.create_line(
                points, fill='#1a73e8', width=2, smooth=True
            )

        # 绘制数据点标记
        for x, y in points:
            self.chart_canvas.create_oval(
                x - 3, y - 3, x + 3, y + 3,
                fill='#1a73e8', outline='white', width=1
            )

        # 标记最新值
        last_ts, last_temp = data[-1]
        last_x, last_y = points[-1]
        self.chart_canvas.create_oval(
            last_x - 5, last_y - 5, last_x + 5, last_y + 5,
            fill='#1a73e8', outline='white', width=2
        )
        self.chart_canvas.create_text(
            last_x, last_y - 14,
            text=f'{last_temp:.1f}°C',
            fill='#1a73e8', font=('Consolas', 9, 'bold')
        )

        # 标记最高/最低值
        max_idx = temps.index(max(temps))
        min_idx = temps.index(min(temps))
        for idx, color, anchor, offset in [
            (max_idx, '#e53935', S, -12),
            (min_idx, '#43a047', N, 12)
        ]:
            px, py = points[idx]
            val = temps[idx]
            self.chart_canvas.create_text(
                px, py + offset,
                text=f'{val:.1f}',
                fill=color, font=('Consolas', 8, 'bold'),
                anchor=anchor
            )

        # 右上角信息
        self.chart_canvas.create_text(
            width - 10, margin_top + 5,
            text=f'最新 {last_temp:.1f}°C  {last_ts.strftime("%H:%M:%S")}',
            anchor=NE, fill='#1a73e8',
            font=('Microsoft YaHei', 10, 'bold')
        )

        if hasattr(self, 'chart_summary_label'):
            self.chart_summary_label.configure(
                text=f'最新: {last_temp:.1f}°C · {last_ts.strftime("%H:%M:%S")} · '
                     f'最高: {max(temps):.1f}°C · 最低: {min(temps):.1f}°C · 点数: {len(data)}'
            )

    def connect_wifi_device(self):
        """通过WIFI连接ADB设备"""
        try:
            import subprocess
            # 首先获取已连接的USB设备
            result = subprocess.run([ADB_PATH, 'devices'], capture_output=True, text=True, encoding='utf-8')
            devices = [line.split('\t')[0] for line in result.stdout.split('\n')[1:] if '\tdevice' in line]
            
            if not devices:
                messagebox.showerror('错误', '请先连接USB设备')
                return
            
            # 获取设备的IP地址
            result = subprocess.run([ADB_PATH, '-s', devices[0], 'shell', 'ifconfig', 'wlan0'], 
                                  capture_output=True, text=True, encoding='utf-8')
            
            # 解析IP地址
            import re
            ip_match = re.search(r'inet addr:(\d+\.\d+\.\d+\.\d+)', result.stdout)
            if not ip_match:
                messagebox.showerror('错误', '无法获取设备IP地址')
                return
            
            device_ip = ip_match.group(1)
            
            # 启动adbd监听
            subprocess.run([ADB_PATH, '-s', devices[0], 'tcpip', '5555'], 
                          capture_output=True, text=True, encoding='utf-8')
            
            # 等待adbd重启
            time.sleep(3)
            
            # 执行adb connect命令
            result = subprocess.run([ADB_PATH, 'connect', f'{device_ip}:5555'], 
                                  capture_output=True, text=True, encoding='utf-8')
            
            # 等待设备连接
            time.sleep(1)
            
            # 检查连接状态
            check_result = subprocess.run([ADB_PATH, 'devices'], capture_output=True, text=True, encoding='utf-8')
            
            if f'{device_ip}:5555' in check_result.stdout:
                self.adb_device_var.set(f'{device_ip}:5555')
                self.save_config()
                messagebox.showinfo('成功', f'成功连接到设备: {device_ip}:5555')
            else:
                error_msg = result.stderr if result.stderr else '设备无响应'
                messagebox.showerror('错误', f'连接失败: {error_msg}')
        except Exception as e:
            messagebox.showerror('错误', f'连接过程中发生错误: {str(e)}')
    
    def connect_usb_device(self):
        """连接USB设备"""
        try:
            # 执行adb devices命令获取设备列表
            import subprocess
            result = subprocess.run([ADB_PATH, 'devices'], capture_output=True, text=True, encoding='utf-8')
            
            # 解析设备列表
            devices = []
            for line in result.stdout.split('\n')[1:]:
                if '\tdevice' in line:
                    devices.append(line.split('\t')[0])
            
            if not devices:
                messagebox.showwarning('警告', '未找到已连接的USB设备')
                return
            
            # 如果只有一个设备，直接使用
            if len(devices) == 1:
                self.adb_device_var.set(devices[0])
                self.save_config()
                messagebox.showinfo('成功', f'已连接到USB设备: {devices[0]}')
            else:
                # 如果有多个设备，弹出选择对话框
                device = self.select_device_dialog(devices)
                if device:
                    self.adb_device_var.set(device)
                if not self.save_config(show_error=True):
                    return
                    messagebox.showinfo('成功', f'已连接到USB设备: {device}')
        except Exception as e:
            messagebox.showerror('错误', f'连接USB设备时发生错误: {str(e)}')
    
    def select_device_dialog(self, devices):
        """创建设备选择对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title('选择设备')
        dialog.geometry('400x300')
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='#f0f0f0')
        dialog.resizable(False, False)
        
        # 设置对话框在屏幕中心显示
        dialog.update_idletasks()
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = (screen_width - dialog.winfo_width()) // 2
        y = (screen_height - dialog.winfo_height()) // 2
        dialog.geometry(f'+{x}+{y}')
        
        # 创建列表框
        listbox = tk.Listbox(dialog)
        listbox.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        # 添加设备列表
        for device in devices:
            listbox.insert(tk.END, device)
        
        # 默认选中第一项
        if devices:
            listbox.select_set(0)
        
        selected_device = None
        
        def on_select():
            nonlocal selected_device
            selection = listbox.curselection()
            if selection:
                selected_device = devices[selection[0]]
                dialog.destroy()
        
        # 添加选择按钮
        select_button = tb.Button(dialog, text='选择', command=on_select)
        select_button.pack(pady=10, ipadx=20, ipady=5)
        
        # 等待对话框关闭
        dialog.wait_window()
        return selected_device

    def start_font_training(self):
        """启动字库训练流程"""
        image_dir = filedialog.askdirectory(title='选择包含训练图片的文件夹')
        if not image_dir:
            return

        output_dir = os.path.join(image_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        image_files = [f for f in os.listdir(image_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tif'))]

        if not image_files:
            messagebox.showinfo('提示', '所选文件夹中没有找到支持的图片文件。')
            return

        tesseract_cmd = pytesseract.pytesseract.tesseract_cmd
        if not tesseract_cmd:
             messagebox.showerror('错误', '未找到Tesseract可执行文件，请先配置Tesseract路径。')
             return

        progress_dialog = tk.Toplevel(self.root)
        progress_dialog.title('生成 .box 文件')
        progress_dialog.geometry('300x100')
        tb.Label(progress_dialog, text='正在生成 .box 文件，请稍候...').pack(pady=20)
        progress_dialog.update()

        # 在单独的线程中运行.box文件生成
        self.box_generation_thread = threading.Thread(target=self._generate_box_files_thread, args=(image_files, image_dir, output_dir, tesseract_cmd, progress_dialog))
        self.box_generation_thread.start()

        # 定期检查线程状态
        self.check_box_generation_thread(progress_dialog, len(image_files), output_dir)

    def _generate_box_files_thread(self, image_files, image_dir, output_dir, tesseract_cmd, progress_dialog):
        """在单独线程中生成.box文件"""
        errors = []
        for i, image_file in enumerate(image_files):
            image_path = os.path.join(image_dir, image_file)
            base_name = os.path.splitext(image_file)[0]
            box_path = os.path.join(output_dir, f'{base_name}.box')

            try:
                # 使用 Tesseract 生成 .box 文件
                # command: tesseract [image_path] [output_base] batch.nochop makebox
                command = [tesseract_cmd, image_path, os.path.join(output_dir, base_name), 'batch.nochop', 'makebox']
                import subprocess
                subprocess.run(command, check=True, capture_output=True, text=True)
                print(f'成功生成 {box_path}')
                # 可以考虑在这里更新进度条或标签
                # progress_dialog.after(0, lambda: progress_label.config(text=f'正在生成 .box 文件 ({i+1}/{len(image_files)})...'))
            except subprocess.CalledProcessError as e:
                errors.append(f'处理文件 {image_file} 失败: {e.stderr}')
            except Exception as e:
                errors.append(f'处理文件 {image_file} 时发生未知错误: {str(e)}')

        # 线程完成后，在主线程中处理结果
        self.root.after(0, self._on_box_generation_complete, progress_dialog, errors, len(image_files), output_dir)

    def check_box_generation_thread(self, progress_dialog, total_files, output_dir):
        """定期检查.box文件生成线程状态"""
        if self.box_generation_thread.is_alive():
            # 线程仍在运行，继续检查
            progress_dialog.after(100, self.check_box_generation_thread, progress_dialog, total_files, output_dir)
        # else: 线程已完成，结果将在_on_box_generation_complete中处理

    def _on_box_generation_complete(self, progress_dialog, errors, total_files, output_dir):
        """在.box文件生成完成后处理结果"""
        progress_dialog.destroy()

        if errors:
            error_msg = '生成 .box 文件时发生错误:\n' + '\n'.join(errors)
            messagebox.showerror('错误', error_msg)
        else:
            messagebox.showinfo('完成', f'已为 {total_files} 张图片生成 .box 文件到 {output_dir} 文件夹。\n请手动校正这些 .box 文件，然后按照Tesseract官方文档进行后续训练步骤。')

    def load_config(self):
        """加载配置文件"""
        print('开始加载配置...', flush=True)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print('成功读取配置文件', flush=True)
                    
                    # 同步界面控件状态
                    print('同步配置到界面控件...', flush=True)
                    self.scale_var.set(str(config.get('scale_factor', 7)))
                    self.clip_var.set(str(config.get('clip_limit', 3.0)))
                    self.alpha_var.set(str(config.get('alpha', 3.0)))
                    self.beta_var.set(str(config.get('beta', 5)))
                    self.invert_var.set(config.get('invert', False))
                    self.threshold_var.set(str(config.get('threshold', 30)))
                    self.interval_var.set(str(config.get('interval', 5)))
                    self.duration_var.set(str(config.get('duration', 60)))
                    
                    # 同步截图方式设置
                    self.capture_mode_var.set(config.get('capture_mode', 'screen'))
                    self.adb_device_var.set(config.get('adb_device', '188.188.22.217:5555'))
                    
                    # 同步识别方式
                    self.ocr_mode_var.set(config.get('ocr_mode', '本地OCR(Tesseract)'))
                    
                    # 同步API提供商
                    api_provider = config.get('api_provider', 'DeepSeek-OCR')
                    self.api_provider_var.set(api_provider)
                    
                    # 同步 SiliconFlow API Key
                    sf_config = config.get('siliconflow', {})
                    self.sf_api_key_var.set(sf_config.get('api_key', ''))
                    self.sf_model_var.set(config.get('sf_model', 'deepseek-ai/DeepSeek-OCR'))
                    
                    # 同步上次打开的标签页
                    active_tab = config.get('active_tab', '测试')
                    if active_tab == '温度曲线':
                        self.root.after(0, lambda: self.notebook.select(self.chart_frame))
                    else:
                        self.root.after(0, lambda: self.notebook.select(self.test_frame))
                    
                    # 同步窗口大小
                    try:
                        window_width = int(config.get('window_width', 1280))
                        window_height = int(config.get('window_height', min(900, self.root.winfo_screenheight() - 80)))
                        window_height = max(650, min(window_height, self.root.winfo_screenheight() - 80))
                        x = max(0, (self.root.winfo_screenwidth() - window_width) // 2)
                        y = max(0, (self.root.winfo_screenheight() - window_height) // 2)
                        self.root.geometry(f'{window_width}x{window_height}+{x}+{y}')
                    except Exception:
                        pass
                    
                    # 获取并显示当前截图区域配置
                    bbox = config.get('bbox', DEFAULT_BBOX)
                    print(f'当前截图区域: x1={bbox[0]}, y1={bbox[1]}, x2={bbox[2]}, y2={bbox[3]}', flush=True)

                    # 加载点击步骤配置（存入 config 字典以确保持久化）
                    config['click_enabled'] = config.get('click_enabled', False)
                    config['click_timing'] = config.get('click_timing', 'before')
                    config['click_steps'] = config.get('click_steps', [])

                    # 加载保存路径
                    save_path = config.get('save_path', '.')
                    self.save_path_var.set(save_path)
                    config['save_path'] = save_path

                    print('配置加载完成', flush=True)
                    return config
            except Exception as e:
                print(f'加载配置文件失败: {str(e)}', flush=True)
                return {}
        else:
            print(f'配置文件 {CONFIG_FILE} 不存在，使用默认配置', flush=True)
            print(f'默认截图区域: x1={DEFAULT_BBOX[0]}, y1={DEFAULT_BBOX[1]}, x2={DEFAULT_BBOX[2]}, y2={DEFAULT_BBOX[3]}', flush=True)
            return {}

    def apply_image_params(self):
        """应用图像处理参数"""
        try:
            # 验证参数有效性
            try:
                scale_factor = float(self.scale_var.get())
                clip_limit = float(self.clip_var.get())
                alpha = float(self.alpha_var.get())
                beta = float(self.beta_var.get())
                threshold = float(self.threshold_var.get())
                interval = int(self.interval_var.get())
                duration = int(self.duration_var.get())
                
                # 验证参数范围
                if scale_factor <= 0:
                    raise ValueError('缩放因子必须大于0')
                if clip_limit <= 0:
                    raise ValueError('CLAHE clipLimit必须大于0')
                if alpha <= 0:
                    raise ValueError('对比度alpha必须大于0')
                if beta < 0:
                    raise ValueError('对比度beta必须大于等于0')
                if threshold < 0 or threshold > 255:
                    raise ValueError('去低色阈值必须在0-255之间')
                if interval <= 0:
                    raise ValueError('截图间隔必须大于0')
                if duration <= 0:
                    raise ValueError('测试时长必须大于0')
                    
                # 更新配置
                self.config['scale_factor'] = scale_factor
                self.config['clip_limit'] = clip_limit
                self.config['alpha'] = alpha
                self.config['beta'] = beta
                self.config['invert'] = bool(self.invert_var.get())
                self.config['threshold'] = threshold
                self.config['interval'] = interval
                self.config['duration'] = duration
                # 保存截图方式设置
                self.config['capture_mode'] = self.capture_mode_var.get()
                self.config['adb_device'] = self.adb_device_var.get()
                if not self.save_config(show_error=True):
                    return
            except ValueError as ve:
                messagebox.showerror('参数错误', str(ve))
                return
            
            # 更新状态
            messagebox.showinfo('成功', '参数已更新')
            
            # 立即更新图像预览
            if hasattr(self, 'last_screenshot'):
                try:
                    # 重新处理上次截图
                    img_np = np.array(self.last_screenshot)
                    gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
                    
                    # 使用新参数处理图像
                    scale_factor = self.config.get('scale_factor', 7)
                    gray = cv2.resize(gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
                    
                    clip_limit = self.config.get('clip_limit', 3.0)
                    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(4,4))
                    gray = clahe.apply(gray)
                    
                    alpha = self.config.get('alpha', 3.0)
                    beta = self.config.get('beta', 5)
                    gray = cv2.convertScaleAbs(gray, alpha=alpha, beta=beta)

                    # 应用去低色阈值
                    threshold_value = self.config.get('threshold', 30)
                    _, mask = cv2.threshold(gray, threshold_value, 255, cv2.THRESH_BINARY)
                    gray = cv2.bitwise_and(gray, mask)

                    # 二值化
                    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

                    # 应用反色值
                    if self.config.get('invert', False):
                        thresh = cv2.bitwise_not(thresh)
                    
                    # 更新预览
                    processed_pil = Image.fromarray(thresh)
                    processed_pil.thumbnail((300, 200))
                    self.processed_photo = ImageTk.PhotoImage(processed_pil)
                    self.processed_label.configure(image=self.processed_photo)
                    
                except Exception as e:
                    print(f'更新预览失败: {str(e)}')
            
            # 如果正在测试，重新获取温度值以应用新参数
            if hasattr(self, 'is_testing') and self.is_testing:
                self.get_temperature()
                
        except ValueError:
            messagebox.showerror('错误', '请输入有效的数字参数')
        
    def save_config(self, show_error=False):
        """保存配置文件"""
        try:
            # 更新配置字典
            self.config.update({
                'scale_factor': float(self.scale_var.get()),
                'clip_limit': float(self.clip_var.get()),
                'alpha': float(self.alpha_var.get()),
                'beta': float(self.beta_var.get()),
                'threshold': float(self.threshold_var.get()),
                'invert': bool(self.invert_var.get()),
                'interval': int(self.interval_var.get()),
                'duration': int(self.duration_var.get()),
                'capture_mode': self.capture_mode_var.get(),
                'adb_device': self.adb_device_var.get(),
                'ocr_mode': self.ocr_mode_var.get(),
                'api_provider': self.api_provider_var.get(),
                'sf_model': self.sf_model_var.get(),
                'active_tab': self.notebook.tab(self.notebook.select(), 'text') if hasattr(self, 'notebook') else '测试',
                'window_width': self.root.winfo_width(),
                'window_height': self.root.winfo_height(),
                'save_path': self.save_path_var.get().strip() or '.'
            })

            # 保存 SiliconFlow API Key
            self.config['siliconflow'] = {'api_key': self.sf_api_key_var.get().strip()}

            # 保存到文件
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f'保存配置失败: {str(e)}', flush=True)
            if show_error:
                messagebox.showerror('保存失败', f'保存配置失败: {str(e)}')
            return False
            
    def select_tesseract_path(self):
        """选择Tesseract-OCR安装路径"""
        path = filedialog.askdirectory(title='选择Tesseract-OCR安装目录')
        if path:
            tesseract_exe = os.path.join(path, 'tesseract.exe')
            if os.path.exists(tesseract_exe):
                self.config['tesseract_path'] = tesseract_exe
                self.save_config()
                pytesseract.pytesseract.tesseract_cmd = tesseract_exe
                # 自动设置 TESSDATA_PREFIX
                tessdata_dir = os.path.join(path, 'tessdata')
                if os.path.exists(os.path.join(tessdata_dir, 'eng.traineddata')):
                    os.environ['TESSDATA_PREFIX'] = tessdata_dir
                messagebox.showinfo('成功', 'Tesseract-OCR路径设置成功！')
                return True
            else:
                messagebox.showerror('错误', '所选目录下未找到tesseract.exe，请确认是否选择了正确的Tesseract-OCR安装目录。')
        return False
        

        
    def check_tesseract(self):
        """检查Tesseract-OCR是否已安装"""
        # 首先尝试使用配置文件中的路径
        if 'tesseract_path' in self.config:
            pytesseract.pytesseract.tesseract_cmd = self.config['tesseract_path']
            # 修复 TESSDATA_PREFIX（系统环境变量可能指向错误路径）
            tesseract_dir = os.path.dirname(self.config['tesseract_path'])
            tessdata_dir = os.path.join(tesseract_dir, 'tessdata')
            if os.path.exists(os.path.join(tessdata_dir, 'eng.traineddata')):
                os.environ['TESSDATA_PREFIX'] = tessdata_dir
        
        try:
            pytesseract.get_tesseract_version()
        except EnvironmentError:
            # 提示用户选择Tesseract-OCR安装路径
            result = messagebox.askquestion('错误', 
                'Tesseract-OCR未安装或未找到。\n'
                '请确保已安装Tesseract-OCR（可从 https://github.com/UB-Mannheim/tesseract/wiki 下载）。\n\n'
                '是否手动选择Tesseract-OCR安装目录？')
            
            if result == 'yes':
                if not self.select_tesseract_path():
                    if messagebox.askquestion('提示', '是否查看详细的安装指南？') == 'yes':
                        os.startfile('INSTALL.md')
                    sys.exit(1)
            else:
                if messagebox.askquestion('提示', '是否查看详细的安装指南？') == 'yes':
                    os.startfile('INSTALL.md')
                sys.exit(1)
    
    def update_image_preview(self, original_image, processed_image):
        """更新图像预览"""
        try:
            print('开始更新图像预览...', flush=True)
            # 转换原始图像格式
            if isinstance(original_image, Image.Image):
                original_pil = original_image
            else:
                original_pil = Image.fromarray(cv2.cvtColor(np.array(original_image), cv2.COLOR_BGR2RGB))
            print('原始图像格式转换完成', flush=True)
            
            # 转换处理后的图像格式
            if isinstance(processed_image, np.ndarray):
                processed_pil = Image.fromarray(processed_image)
            else:
                processed_pil = processed_image
            print('处理后图像格式转换完成', flush=True)
            
            # 等待窗口更新完成
            self.image_frame.update_idletasks()
            self.image_panes.update_idletasks()
            
            # 获取预览区域的实际大小
            preview_width = (self.image_panes.winfo_width() - 20) // 2  # 减去padding和分隔符宽度
            preview_height = self.image_panes.winfo_height() - 20  # 减去padding和标题栏高度
            print(f'预览区域尺寸: {preview_width}x{preview_height}', flush=True)
            
            # 确保最小尺寸
            preview_width = max(preview_width, 300)
            preview_height = max(preview_height, 200)
            max_size = (preview_width, preview_height)
            print(f'调整后的预览区域尺寸: {max_size}', flush=True)
            
            # 等比例缩放图像
            def resize_image(img, max_size):
                # 计算缩放比例，优先填充宽度
                ratio_w = max_size[0] / img.size[0]
                ratio_h = max_size[1] / img.size[1]
                ratio = min(ratio_w, ratio_h)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                print(f'图像缩放比例: {ratio:.2f}, 新尺寸: {new_size}', flush=True)
                return img.resize(new_size, Image.LANCZOS)
            
            # 调整图像大小
            original_pil = resize_image(original_pil, max_size)
            processed_pil = resize_image(processed_pil, max_size)
            print('图像缩放完成', flush=True)
            
            # 转换为PhotoImage
            self.original_photo = ImageTk.PhotoImage(original_pil)
            self.processed_photo = ImageTk.PhotoImage(processed_pil)
            print('PhotoImage转换完成', flush=True)
            
            # 更新标签
            self.original_label.configure(image=self.original_photo, anchor='center')
            self.processed_label.configure(image=self.processed_photo, anchor='center')
            print('标签更新完成', flush=True)
        except Exception as e:
            print(f'更新图像预览失败：{str(e)}', flush=True)
    
    def open_image_folder(self):
        """打开保存图片的文件夹"""
        sp = self._get_save_paths()
        if os.path.exists(sp['png']):
            os.startfile(sp['png'])
        else:
            messagebox.showerror('错误', '图片文件夹不存在')
    
    def export_data(self):
        """导出测试数据到CSV文件"""
        if not self.test_data:
            messagebox.showinfo('提示', '没有可导出的数据')
            return
        
        from tkinter import filedialog
        file_path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            filetypes=[('CSV文件', '*.csv'), ('所有文件', '*.*')],
            title='导出测试数据'
        )
        if not file_path:
            return
        
        try:
            import csv
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['时间', '温度值(°C)'])
                for timestamp, temp in self.test_data:
                    writer.writerow([timestamp, f'{temp:.1f}'])
            messagebox.showinfo('成功', f'数据已导出到:\n{file_path}')
        except Exception as e:
            messagebox.showerror('导出失败', str(e))
    
    def configure_bbox(self):
        """配置截图区域"""
        print('开始配置截图区域...', flush=True)
        was_testing = self.is_testing
        if was_testing:
            self.stop_test()

        dialog = tk.Toplevel(self.root)
        dialog.title('设置截图区域')
        dialog.geometry('1100x700')
        dialog.transient(self.root)

        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() - width) // 2
        y = (dialog.winfo_screenheight() - height) // 2
        dialog.geometry(f'+{x}+{y}')
        print('配置对话框创建完成', flush=True)

        current_bbox = self.config.get('bbox', DEFAULT_BBOX)
        click_enabled = self.config.get('click_enabled', False)
        click_steps = self.config.get('click_steps', [])

        left_panel = tb.Frame(dialog)
        left_panel.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.Y)

        bbox_frame = tb.LabelFrame(left_panel, text='截图区域')
        bbox_frame.pack(fill=tk.X, pady=(0, 8))

        tb.Label(bbox_frame, text='左上角 X:').grid(row=0, column=0, padx=5, pady=3, sticky=E)
        left_entry = tb.Entry(bbox_frame, width=10)
        left_entry.insert(0, str(current_bbox[0]))
        left_entry.grid(row=0, column=1, padx=5, pady=3)

        tb.Label(bbox_frame, text='左上角 Y:').grid(row=1, column=0, padx=5, pady=3, sticky=E)
        top_entry = tb.Entry(bbox_frame, width=10)
        top_entry.insert(0, str(current_bbox[1]))
        top_entry.grid(row=1, column=1, padx=5, pady=3)

        tb.Label(bbox_frame, text='右下角 X:').grid(row=2, column=0, padx=5, pady=3, sticky=E)
        right_entry = tb.Entry(bbox_frame, width=10)
        right_entry.insert(0, str(current_bbox[2]))
        right_entry.grid(row=2, column=1, padx=5, pady=3)

        tb.Label(bbox_frame, text='右下角 Y:').grid(row=3, column=0, padx=5, pady=3, sticky=E)
        bottom_entry = tb.Entry(bbox_frame, width=10)
        bottom_entry.insert(0, str(current_bbox[3]))
        bottom_entry.grid(row=3, column=1, padx=5, pady=3)

        click_frame = tb.LabelFrame(left_panel, text='ADB 点击步骤')
        click_frame.pack(fill=tk.BOTH, expand=YES)

        click_enable_var = tk.BooleanVar(value=click_enabled)
        tb.Checkbutton(click_frame, text='启用点击功能', variable=click_enable_var).pack(anchor=tk.W, padx=5, pady=4)

        timing_frame = tb.Frame(click_frame)
        timing_frame.pack(anchor=tk.W, padx=5, pady=2)
        tb.Label(timing_frame, text='点击时机:').pack(side=tk.LEFT)
        click_timing_var = tk.StringVar(value=self.config.get('click_timing', 'before'))
        tb.Radiobutton(timing_frame, text='截图前', variable=click_timing_var, value='before').pack(side=tk.LEFT, padx=4)
        tb.Radiobutton(timing_frame, text='截图后', variable=click_timing_var, value='after').pack(side=tk.LEFT, padx=4)

        mode_hint = tk.StringVar(value='')
        mode_hint_label = tb.Label(click_frame, textvariable=mode_hint, foreground='blue', font=('Arial', 8))
        mode_hint_label.pack(anchor=tk.W, padx=5)

        def on_click_enable_toggle():
            if click_enable_var.get():
                if not click_steps:
                    mode_hint.set('请先点"添加步骤"，然后点击截图选取位置')
                else:
                    remaining = sum(1 for s in click_steps if s['x'] == 0 and s['y'] == 0)
                    if remaining > 0:
                        mode_hint.set(f'点击模式已开启，还有 {remaining} 步待设置位置')
                    else:
                        mode_hint.set('点击模式已开启，所有步骤位置已设置')
            else:
                mode_hint.set('')

        click_enable_var.trace_add('write', lambda *_: on_click_enable_toggle())
        on_click_enable_toggle()

        tree_frame = tb.Frame(click_frame)
        tree_frame.pack(fill=tk.BOTH, expand=YES, padx=5, pady=2)

        steps_columns = ('序号', 'X', 'Y', '延迟(秒)')
        steps_tree = tb.Treeview(tree_frame, columns=steps_columns, show='headings', height=6)
        steps_tree.heading('序号', text='#')
        steps_tree.heading('X', text='X')
        steps_tree.heading('Y', text='Y')
        steps_tree.heading('延迟(秒)', text='延迟(秒)')
        steps_tree.column('序号', width=30, stretch=False)
        steps_tree.column('X', width=60, stretch=False)
        steps_tree.column('Y', width=60, stretch=False)
        steps_tree.column('延迟(秒)', width=70, stretch=False)
        steps_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=YES)

        steps_scrollbar = tb.Scrollbar(tree_frame, orient=tk.VERTICAL, command=steps_tree.yview)
        steps_tree.configure(yscrollcommand=steps_scrollbar.set)
        steps_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def refresh_steps_tree():
            for item in steps_tree.get_children():
                steps_tree.delete(item)
            for i, s in enumerate(click_steps):
                steps_tree.insert('', 'end', values=(i + 1, s['x'], s['y'], s['delay']))

        refresh_steps_tree()

        btn_row = tb.Frame(click_frame)
        btn_row.pack(fill=tk.X, padx=5, pady=4)

        def on_step_select(event):
            sel = steps_tree.selection()
            if sel:
                values = steps_tree.item(sel[0], 'values')
                idx = int(values[0]) - 1
                mode_hint.set(f'步骤 {idx + 1}: X={click_steps[idx]["x"]}, Y={click_steps[idx]["y"]}, 延迟={click_steps[idx]["delay"]}s')

        steps_tree.bind('<<TreeviewSelect>>', on_step_select)

        def add_step():
            delay_val = 1.0
            click_steps.append({'x': 0, 'y': 0, 'delay': delay_val})
            refresh_steps_tree()
            new_children = steps_tree.get_children()
            if new_children:
                steps_tree.selection_set(new_children[-1])
                steps_tree.see(new_children[-1])

        def remove_step():
            sel = steps_tree.selection()
            if not sel:
                messagebox.showwarning('提示', '请先选择要删除的步骤')
                return
            values = steps_tree.item(sel[0], 'values')
            idx = int(values[0]) - 1
            if 0 <= idx < len(click_steps):
                click_steps.pop(idx)
                state['next_click_idx'] = max(0, min(state['next_click_idx'], len(click_steps)))
                refresh_steps_tree()
                mode_hint.set('')

        def edit_step_delay():
            sel = steps_tree.selection()
            if not sel:
                messagebox.showwarning('提示', '请先选择步骤')
                return
            values = steps_tree.item(sel[0], 'values')
            idx = int(values[0]) - 1
            if 0 <= idx < len(click_steps):
                delay_dialog = tk.Toplevel(dialog)
                delay_dialog.title(f'设置步骤 {idx + 1} 延迟')
                delay_dialog.geometry('280x120')
                delay_dialog.transient(dialog)
                delay_dialog.grab_set()

                tb.Label(delay_dialog, text='点击后延迟(秒):').pack(padx=10, pady=(15, 5))
                delay_var = tk.StringVar(value=str(click_steps[idx]['delay']))
                delay_entry = tb.Entry(delay_dialog, textvariable=delay_var, width=15)
                delay_entry.pack(padx=10)
                delay_entry.select_range(0, tk.END)
                delay_entry.focus_set()

                def confirm_delay():
                    try:
                        new_delay = float(delay_var.get())
                        if new_delay < 0:
                            raise ValueError
                        click_steps[idx]['delay'] = new_delay
                        refresh_steps_tree()
                        delay_dialog.destroy()
                    except (ValueError, TypeError):
                        messagebox.showerror('错误', '请输入有效的正数')

                tb.Button(delay_dialog, text='确定', command=confirm_delay, style='success.TButton').pack(pady=8)

        def clear_steps():
            if click_steps and messagebox.askyesno('确认', '确定清空所有点击步骤?'):
                click_steps.clear()
                state['next_click_idx'] = 0
                refresh_steps_tree()
                mode_hint.set('')

        tb.Button(btn_row, text='添加步骤', command=add_step, style='success.TButton').pack(side=tk.LEFT, padx=2)
        tb.Button(btn_row, text='删除步骤', command=remove_step, style='danger.TButton').pack(side=tk.LEFT, padx=2)
        tb.Button(btn_row, text='设置延迟', command=edit_step_delay, style='info.TButton').pack(side=tk.LEFT, padx=2)
        tb.Button(btn_row, text='清空', command=clear_steps, style='secondary.TButton').pack(side=tk.LEFT, padx=2)

        preview_frame = tb.Frame(dialog)
        preview_frame.pack(side=tk.RIGHT, padx=10, pady=10, expand=True, fill=tk.BOTH)

        canvas = tk.Canvas(preview_frame, bg='#2b2b2b')
        canvas.pack(expand=True, fill=tk.BOTH)

        screenshot_array = self.capture_screen(crop=False)

        state = {
            'scale_x': 1.0, 'scale_y': 1.0,
            'rect_id': None, 'start_x': 0, 'start_y': 0,
            'dragging_rect': False,
            'click_markers': [],
            'next_click_idx': 0,
        }

        def redraw_click_markers():
            for marker_id in state['click_markers']:
                canvas.delete(marker_id)
            state['click_markers'].clear()
            for i, s in enumerate(click_steps):
                cx = s['x'] * state['scale_x']
                cy = s['y'] * state['scale_y']
                r = 8
                mid = canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                         outline='#00ff00', width=2, fill='')
                txt = canvas.create_text(cx, cy - r - 10, text=str(i + 1),
                                         fill='#00ff00', font=('Arial', 9, 'bold'))
                state['click_markers'].extend([mid, txt])

        def find_next_unassigned():
            for i, s in enumerate(click_steps):
                if s['x'] == 0 and s['y'] == 0:
                    return i
            return 0 if click_steps else -1

        if screenshot_array is not None:
            image = Image.fromarray(cv2.cvtColor(screenshot_array, cv2.COLOR_BGR2RGB))
            image.thumbnail((600, 500))
            photo = ImageTk.PhotoImage(image)
            canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            canvas.image = photo

            state['scale_x'] = image.size[0] / screenshot_array.shape[1]
            state['scale_y'] = image.size[1] / screenshot_array.shape[0]

            state['rect_id'] = canvas.create_rectangle(
                current_bbox[0] * state['scale_x'],
                current_bbox[1] * state['scale_y'],
                current_bbox[2] * state['scale_x'],
                current_bbox[3] * state['scale_y'],
                outline='red', width=2
            )

            def on_mouse_down(event):
                state['start_x'] = event.x
                state['start_y'] = event.y

                if click_enable_var.get() and click_steps:
                    real_x = int(event.x / state['scale_x'])
                    real_y = int(event.y / state['scale_y'])
                    idx = find_next_unassigned()
                    if idx < 0:
                        idx = state['next_click_idx'] % len(click_steps)
                    click_steps[idx]['x'] = real_x
                    click_steps[idx]['y'] = real_y
                    state['next_click_idx'] = idx + 1
                    refresh_steps_tree()
                    redraw_click_markers()
                    steps_children = steps_tree.get_children()
                    if idx < len(steps_children):
                        steps_tree.selection_set(steps_children[idx])
                        steps_tree.see(steps_children[idx])
                    remaining = len(click_steps) - state['next_click_idx']
                    if remaining > 0:
                        mode_hint.set(f'步骤 {idx + 1} 已设置，还有 {remaining} 步待设置，继续点击')
                    else:
                        mode_hint.set(f'步骤 {idx + 1} 已设置，所有步骤位置已设置完成！')
                    return

                state['dragging_rect'] = True
                canvas.coords(state['rect_id'], event.x, event.y, event.x, event.y)

            def on_mouse_drag(event):
                if not state['dragging_rect']:
                    return
                canvas.coords(state['rect_id'], state['start_x'], state['start_y'], event.x, event.y)

                x1, x2 = sorted([state['start_x'], event.x])
                y1, y2 = sorted([state['start_y'], event.y])
                left_entry.delete(0, tk.END)
                left_entry.insert(0, str(int(x1 / state['scale_x'])))
                top_entry.delete(0, tk.END)
                top_entry.insert(0, str(int(y1 / state['scale_y'])))
                right_entry.delete(0, tk.END)
                right_entry.insert(0, str(int(x2 / state['scale_x'])))
                bottom_entry.delete(0, tk.END)
                bottom_entry.insert(0, str(int(y2 / state['scale_y'])))

            def on_mouse_up(event):
                state['dragging_rect'] = False

            canvas.bind('<Button-1>', on_mouse_down)
            canvas.bind('<B1-Motion>', on_mouse_drag)
            canvas.bind('<ButtonRelease-1>', on_mouse_up)

            redraw_click_markers()

        def save_all():
            try:
                new_bbox = (
                    int(left_entry.get()),
                    int(top_entry.get()),
                    int(right_entry.get()),
                    int(bottom_entry.get())
                )
                self.config['bbox'] = new_bbox
                self.config['click_enabled'] = click_enable_var.get()
                self.config['click_timing'] = click_timing_var.get()
                self.config['click_steps'] = list(click_steps)
                self.save_config()
                messagebox.showinfo('成功', '设置已保存')
                dialog.destroy()
                if was_testing:
                    self.start_test()
            except ValueError:
                messagebox.showerror('错误', '请输入有效的数字')

        save_btn_frame = tb.Frame(left_panel)
        save_btn_frame.pack(fill=tk.X, pady=(8, 0))
        tb.Button(save_btn_frame, text='保存设置', command=save_all, style='success.TButton').pack(fill=tk.X)

    def _run_click_steps_once(self):
        """执行一轮点击步骤（在测试线程中同步调用）"""
        click_steps = self.config.get('click_steps', [])
        device = self.adb_device_var.get().strip()
        if not device or not click_steps:
            return
        import subprocess
        for i, step in enumerate(click_steps):
            x = step['x']
            y = step['y']
            delay = step.get('delay', 1.0)
            try:
                subprocess.run(
                    [ADB_PATH, '-s', device, 'shell', 'input', 'tap', str(x), str(y)],
                    capture_output=True, timeout=10
                )
            except Exception as e:
                print(f'点击步骤 {i + 1} 异常: {str(e)}', flush=True)
            if delay > 0:
                time.sleep(delay)

    def _get_save_paths(self):
        """获取配置的保存路径相关文件夹"""
        base = self.config.get('save_path', '.')
        png_folder = os.path.join(base, 'png')
        raw_folder = os.path.join(png_folder, 'raw_images')
        original_folder = os.path.join(png_folder, 'original_images')
        csv_folder = os.path.join(base, 'csv')
        debug_folder = os.path.join(base, 'debug')
        return {
            'base': base,
            'png': png_folder,
            'raw': raw_folder,
            'original': original_folder,
            'csv': csv_folder,
            'debug': debug_folder,
        }

    def _ensure_save_dirs(self, paths):
        """确保保存路径文件夹存在"""
        for key in ['png', 'raw', 'original', 'csv', 'debug']:
            folder = paths[key]
            if not os.path.exists(folder):
                os.makedirs(folder)

    def _browse_save_path(self):
        path = filedialog.askdirectory(title='选择截图保存目录')
        if path:
            self.save_path_var.set(path)
            self.config['save_path'] = path
            self.save_config()

    def get_temperature(self):
        """获取温度值"""
        try:
            time.sleep(0.2)

            screenshot_array = self.capture_screen(crop=False)
            if screenshot_array is None:
                return

            paths = self._get_save_paths()
            self._ensure_save_dirs(paths)

            current_time = time.strftime("%Y%m%d_%H%M%S")
            original_filename = os.path.join(paths['original'], f'original_{current_time}.png')
            raw_filename = os.path.join(paths['raw'], f'raw_{current_time}.png')
            processed_filename = os.path.join(paths['png'], f'processed_{current_time}.png')
            
            # 检查截图是否有效
            if screenshot_array is None or screenshot_array.size == 0:
                raise ValueError('截图获取失败或图像为空')
                
            # 保存裁剪前的原始截图
            # 保存裁剪前的原始截图
            original_pil = Image.fromarray(cv2.cvtColor(screenshot_array, cv2.COLOR_BGR2RGB))
            original_pil.save(original_filename, 'PNG', dpi=(120, 120), bits=24)
            
            # 获取裁剪区域
            bbox = self.config.get('bbox', DEFAULT_BBOX)
            x1, y1, x2, y2 = bbox
            
            # 验证裁剪区域是否有效
            if x1 >= x2 or y1 >= y2:
                raise ValueError('无效的裁剪区域：坐标值错误')
            if x2 > screenshot_array.shape[1] or y2 > screenshot_array.shape[0]:
                raise ValueError('无效的裁剪区域：超出图像范围')
            
            # 裁剪图像
            try:
                cropped_array = screenshot_array[y1:y2, x1:x2]
                if cropped_array.size == 0:
                    raise ValueError('裁剪后的图像为空')
            except Exception as e:
                raise ValueError(f'图像裁剪失败：{str(e)}')
            
            # 保存裁剪后的原始截图，设置DPI和位深度
            cropped_pil = Image.fromarray(cv2.cvtColor(cropped_array, cv2.COLOR_BGR2RGB))
            cropped_pil.save(raw_filename, 'PNG', dpi=(120, 120), bits=24)
            
            # 保存最后一次截图用于参数调整后重新处理
            self.last_screenshot = cropped_array.copy()
            
            # 转换为灰度图
            gray = cv2.cvtColor(cropped_array, cv2.COLOR_BGR2GRAY)
            
            # 放大图像
            scale_factor = self.config.get('scale_factor', 7)
            gray = cv2.resize(gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
            
            # 二值化处理
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # 形态学处理
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
            
            # 保存处理后的图像，设置DPI和位深度
            processed_pil = Image.fromarray(thresh)
            processed_pil = processed_pil.convert('RGB')  # 24位深度
            processed_pil.save(processed_filename, 'PNG', dpi=(120, 120), bits=24)
            
            # 垂直方向的闭运算
            kernel_vertical = cv2.getStructuringElement(cv2.MORPH_RECT, (1,3))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel_vertical, iterations=2)
            
            # 水平方向的闭运算
            kernel_horizontal = cv2.getStructuringElement(cv2.MORPH_RECT, (3,1))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel_horizontal, iterations=1)
            
            # 将处理后的图像缩放回原始大小
            cropped_height, cropped_width = cropped_array.shape[:2]
            thresh = cv2.resize(thresh, (cropped_width, cropped_height), interpolation=cv2.INTER_AREA)
            
            # 应用反色值
            if self.config.get('invert', False):
                thresh = cv2.bitwise_not(thresh)
            
            # 保存处理后的图像
            final_pil = Image.fromarray(thresh)
            final_pil = final_pil.convert('RGB')  # 24位深度
            final_pil.save(processed_filename, 'PNG', dpi=(120, 120), bits=24)
            
            # 保存图像数据用于主线程更新预览
            self._last_cropped = cropped_array.copy()
            self._last_thresh = thresh.copy()
            
            # 根据选择的识别方式执行OCR
            ocr_mode = self.ocr_mode_var.get()
            
            if ocr_mode == 'API识别(硅基)':
                # API方式：将处理后的图片发给硅基API
                api_key = self.sf_api_key_var.get().strip()
                if not api_key:
                    raise ValueError('API Key 未配置')
                
                from ocr_deepseek import recognize as api_recognize
                api_text = api_recognize(processed_filename, api_key=api_key, model=self.sf_model_var.get())
                temp = None
                if api_text:
                    import re
                    nums = re.findall(r'[\d.]+', api_text.replace('-', '.-'))
                    for n in nums:
                        try:
                            val = float(n)
                            if -50 < val < 200:
                                temp = val
                                break
                        except:
                            pass
                
                if temp is not None:
                    return temp
                else:
                    print(f'API识别未提取到温度: {api_text}', flush=True)
                    return None
            else:
                # 本地Tesseract OCR
                text = pytesseract.image_to_string(thresh, config='--psm 6 --oem 3 -c tessedit_char_whitelist=-.0123456789')
                
                # 提取数字和负号
                numbers = ''.join(c for c in text if c.isdigit() or c == '.')
                is_negative = '-' in text
            
            if not numbers:
                print(f'错误: 未能识别到数字，裁剪前原始截图已保存在 {paths["original"]} 文件夹中，裁剪后原始截图在 {paths["raw"]} 文件夹中，处理后的图像在 {paths["png"]} 文件夹中，请检查截图区域是否正确。')
                return None
            
            temp = float(numbers)
            if is_negative:
                temp = -temp
                
            if temp < -273.15 or temp > 1000:
                print(f'错误: 识别到的温度值 {temp}°C 超出合理范围，裁剪前原始截图已保存在 {paths["original"]} 文件夹中，裁剪后原始截图在 {paths["raw"]} 文件夹中，处理后的图像在 {paths["png"]} 文件夹中。')
                return None
            
            return temp
        except Exception as e:
            print(f'错误: 温度读取错误: {str(e)}')
            return None
    
    def start_test(self):
        try:
            interval = int(self.interval_var.get())
            duration = int(self.duration_var.get())
            
            if interval <= 0 or duration <= 0:
                raise ValueError('时间参数必须大于0')
                
            self.is_testing = True
            self.start_btn.configure(state=DISABLED)
            self.stop_btn.configure(state=NORMAL)
            self.test_data = []
            self.chart_data = []
            
            # 记录开始时间
            self.start_time = time.time()
            self.total_duration = duration * 60
            
            # 启动测试循环
            self.root.after(0, self.test_loop, interval)
            
        except ValueError as e:
            tk.messagebox.showerror('错误', str(e))
    
    def test_loop(self, interval):
        if not self.is_testing:
            self.stop_test()
            return
        
        # 计算剩余时间
        elapsed_time = time.time() - self.start_time
        remaining_time = self.total_duration - elapsed_time
        
        if remaining_time <= 0:
            self.stop_test()
            return
        
        # 更新进度显示
        hours = int(remaining_time // 3600)
        minutes = int((remaining_time % 3600) // 60)
        seconds = int(remaining_time % 60)
        progress_text = f'剩余时间: {hours:02d}:{minutes:02d}:{seconds:02d}'
        self.progress_label.configure(text=f'{progress_text} (识别中...)')
        
        # 在后台线程中执行截图 + OCR，避免卡界面
        threading.Thread(target=self._read_temp_thread, args=(interval,), daemon=True).start()
    
    def _read_temp_thread(self, interval):
        """后台线程：截图 + 图像处理 + OCR"""
        try:
            click_enabled = self.config.get('click_enabled', False)
            click_timing = self.config.get('click_timing', 'before')

            if click_enabled and click_timing == 'before':
                self._run_click_steps_once()

            temp = self.get_temperature()

            if click_enabled and click_timing == 'after':
                self._run_click_steps_once()

            self.root.after(0, self._on_temp_received, temp, interval)
        except Exception as e:
            print(f'温度读取线程错误: {str(e)}', flush=True)
            self.root.after(0, self._on_temp_received, None, interval)
    
    def _on_temp_received(self, temp, interval):
        """主线程：更新界面显示"""
        # 在主线程中更新图像预览（线程安全）
        if hasattr(self, '_last_cropped') and hasattr(self, '_last_thresh'):
            try:
                self.update_image_preview(self._last_cropped, self._last_thresh)
            except Exception as e:
                print(f'更新预览失败: {str(e)}', flush=True)
        
        if temp is not None:
            self.temp_label.configure(text=f'{temp}°C')
            # 记录数据
            timestamp_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            timestamp = datetime.now()
            self.test_data.append((timestamp_text, temp))
            self.add_chart_data(timestamp, temp)
            self.tree.insert('', 'end', values=(timestamp_text, temp))
            # 自动滚动到最新数据
            self.tree.yview_moveto(1)
        
        # 更新进度（去掉"识别中"状态）
        elapsed_time = time.time() - self.start_time
        remaining_time = self.total_duration - elapsed_time
        if remaining_time > 0:
            hours = int(remaining_time // 3600)
            minutes = int((remaining_time % 3600) // 60)
            seconds = int(remaining_time % 60)
            self.progress_label.configure(text=f'剩余时间: {hours:02d}:{minutes:02d}:{seconds:02d}')
        
        # 继续循环
        if self.is_testing:
            self.root.after(interval * 1000, self.test_loop, interval)
    
    def stop_test(self):
        self.is_testing = False
        self.start_btn.configure(state=NORMAL)
        self.stop_btn.configure(state=DISABLED)
        
        # 清除进度显示
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(text='')
        
        # 保存测试数据
        if self.test_data:
            paths = self._get_save_paths()
            if not os.path.exists(paths['csv']):
                os.makedirs(paths['csv'])
            
            df = pd.DataFrame(self.test_data, columns=['时间', '温度值'])
            filename = os.path.join(paths['csv'], f'temperature_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            tk.messagebox.showinfo('提示', f'测试已完成，数据已保存至{filename}')
            
            # 清空数据列表
            self.test_data = []





    def api_recognize(self):
        """使用API进行OCR识别（支持讯飞/DeepSeek-OCR）"""
        try:
            screenshot_array = self.capture_screen(crop=True)
            if screenshot_array is None:
                messagebox.showerror('错误', '截图失败')
                return

            sp = self._get_save_paths()
            self._ensure_save_dirs(sp)

            current_time = time.strftime("%Y%m%d_%H%M%S")
            processed_filename = os.path.join(sp['png'], f'api_processed_{current_time}.png')
            
            # 用与get_temperature相同的图像处理流程生成二值化图片
            gray = cv2.cvtColor(screenshot_array, cv2.COLOR_BGR2GRAY)
            
            # 二值化处理（全屏图直接Otsu，不做缩放）
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # 保存处理后的图像
            cv2.imwrite(processed_filename, thresh)
            
            # 保存预览（原始彩色图）
            screenshot_rgb = cv2.cvtColor(screenshot_array, cv2.COLOR_BGR2RGB)
            screenshot_pil = Image.fromarray(screenshot_rgb)
            self.last_screenshot = screenshot_pil.copy()
            self.last_processed = thresh.copy()
            self.update_image_preview(screenshot_pil, thresh)
            
            # 根据选择的提供商调用对应API
            provider = self.api_provider_var.get()
            
            if provider == 'DeepSeek-OCR':
                self._call_deepseek_ocr(processed_filename)
            else:
                self._call_xunfei_ocr(processed_filename)
                
        except Exception as e:
            messagebox.showerror('错误', f'API识别失败：{str(e)}')
    
    def _call_deepseek_ocr(self, image_path):
        """调用 DeepSeek-OCR / Nex-N2-Pro（硅基流动）"""
        try:
            api_key = self.sf_api_key_var.get().strip()
            if not api_key:
                messagebox.showerror('配置错误', '请先填写 SiliconFlow API Key')
                return
            
            from ocr_deepseek import recognize as deepseek_recognize
            
            text = deepseek_recognize(image_path, api_key=api_key, model=self.sf_model_var.get())
            temp = None
            if text:
                import re
                nums = re.findall(r'[\d.]+', text.replace('-', '.-'))
                for n in nums:
                    try:
                        val = float(n)
                        if -50 < val < 200:
                            temp = val
                            break
                    except:
                        pass
            
            if temp is not None:
                self.temp_label.configure(text=f'{temp:.1f}°C')
                timestamp = datetime.now()
                self.test_data.append((timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], temp))
                self.add_chart_data(timestamp, temp)
                self.tree.insert('', 'end', values=(timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], f'{temp:.1f}'))
                self.tree.yview_moveto(1)
                print(f'API识别成功: {temp:.1f}°C', flush=True)
            else:
                print(f'API识别未提取到温度: {text}', flush=True)
                
        except ValueError as e:
            messagebox.showerror('配置错误', f'API配置错误：{str(e)}')
        except requests.exceptions.RequestException as e:
            messagebox.showerror('网络错误', f'API请求失败：{str(e)}')
        except Exception as e:
            messagebox.showerror('识别错误', f'API识别失败：{str(e)}')
    
    def _call_xunfei_ocr(self, image_path):
        """调用讯飞OCR"""
        try:
            from ocr_mix_instig import universalOcr, get_result
            
            # 创建OCR实例并识别
            ocr = universalOcr()
            get_result(ocr, image_path)
            messagebox.showinfo('提示', '讯飞OCR识别完成，请查看控制台输出')
            
        except ValueError as e:
            messagebox.showerror('配置错误', f'API配置错误：{str(e)}\n请检查config.json文件中的API密钥信息。')
        except requests.exceptions.RequestException as e:
            messagebox.showerror('网络错误', f'API请求失败：{str(e)}\n请检查网络连接。')
        except Exception as e:
            messagebox.showerror('识别错误', f'OCR识别失败：{str(e)}')

    def capture_screen(self, crop=True):
        """获取屏幕截图
        Args:
            crop: True=返回裁剪后的区域图(供温度识别), False=返回全屏截图(供设置区域)
        """
        if self.capture_mode_var.get() == 'adb':
            # 检查ADB设备参数
            device = self.adb_device_var.get().strip()
            if not device:
                messagebox.showerror('错误', '请输入ADB设备参数')
                return None
                
            bbox = self.config.get('bbox', DEFAULT_BBOX)
            x1, y1, x2, y2 = bbox
            
            try:
                import subprocess
                
                # ADB 统一使用全屏截图，然后在 PC 端裁剪
                # 这样兼容所有 Android 版本，无需依赖 --crop 参数
                proc = subprocess.run(
                    [ADB_PATH, '-s', device, 'exec-out', 'screencap', '-p'],
                    capture_output=True, timeout=15
                )
                if proc.returncode != 0 or len(proc.stdout) == 0:
                    stderr_info = proc.stderr.decode('utf-8', errors='replace') if proc.stderr else '无错误输出'
                    print(f'ADB截图失败, returncode={proc.returncode}, stderr={stderr_info}', flush=True)
                    raise ValueError(f'ADB截图返回空数据 (err: {stderr_info})')
                
                # 从内存解码 PNG
                img_array = np.frombuffer(proc.stdout, dtype=np.uint8)
                image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError('图片解码失败')
                
                if crop:
                    # PC 端裁剪
                    height, width = image.shape[:2]
                    if x2 > width or y2 > height:
                        raise ValueError(f'裁剪区域({x2},{y2})超出图像范围({width}x{height})')
                    return image[y1:y2, x1:x2]
                else:
                    return image
                
            except subprocess.TimeoutExpired:
                print('错误: ADB截图超时，请检查设备连接', flush=True)
                messagebox.showerror('错误', 'ADB截图超时，请检查设备连接')
                return None
            except Exception as e:
                print(f'错误: ADB截图失败: {str(e)}', flush=True)
                messagebox.showerror('错误', f'ADB截图失败：{str(e)}')
                return None
        else:
            try:
                # 进行全屏截图
                print('开始全屏截图...', flush=True)
                try:
                    screenshot = ImageGrab.grab()
                    if screenshot is None:
                        raise ValueError('截图返回为空')
                    print(f'截图尺寸: {screenshot.size}', flush=True)
                except Exception as e:
                    print(f'截图失败: {str(e)}', flush=True)
                    raise ValueError(f'无法获取屏幕截图: {str(e)}')
                
                # 转换为OpenCV格式
                try:
                    screenshot_array = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
                    if screenshot_array is None:
                        raise ValueError('图像转换后为空')
                    height, width = screenshot_array.shape[:2]
                    print(f'转换后图像尺寸: {width}x{height}', flush=True)
                except Exception as e:
                    print(f'图像格式转换失败: {str(e)}', flush=True)
                    # 保存原始截图以供调试
                    try:
                        sp = self._get_save_paths()
                        self._ensure_save_dirs(sp)
                        debug_path = os.path.join(sp['debug'], f'screenshot_{int(time.time())}.png')
                        screenshot.save(debug_path)
                        print(f'原始截图已保存至: {debug_path}', flush=True)
                    except Exception as save_error:
                        print(f'保存调试截图失败: {str(save_error)}', flush=True)
                    raise ValueError(f'图像格式转换失败: {str(e)}')
                
                # 根据参数决定是否裁剪
                if crop:
                    # 获取裁剪区域参数
                    bbox = self.config.get('bbox', DEFAULT_BBOX)
                    x1, y1, x2, y2 = bbox
                    print(f'裁剪区域参数: x1={x1}, y1={y1}, x2={x2}, y2={y2}', flush=True)
                    
                    # 验证裁剪区域是否有效
                    if x1 >= x2 or y1 >= y2:
                        print('裁剪区域坐标值错误', flush=True)
                        raise ValueError('无效的裁剪区域：坐标值错误')
                    if x2 > width or y2 > height:
                        print(f'裁剪区域超出图像范围 (图像尺寸: {width}x{height})', flush=True)
                        raise ValueError(f'无效的裁剪区域：超出图像范围 (图像尺寸: {width}x{height})')
                    
                    # 裁剪图像
                    try:
                        cropped_array = screenshot_array[y1:y2, x1:x2]
                        if cropped_array is None or cropped_array.size == 0:
                            print('裁剪后的图像为空', flush=True)
                            raise ValueError('裁剪后的图像为空')
                        print(f'裁剪后图像尺寸: {cropped_array.shape[1]}x{cropped_array.shape[0]}', flush=True)
                        return cropped_array
                    except Exception as e:
                        print(f'图像裁剪失败: {str(e)}', flush=True)
                        raise ValueError(f'图像裁剪失败: {str(e)}')
                else:
                    # 返回全屏截图（用于设置截图区域）
                    return screenshot_array
            except Exception as e:
                print(f'截图过程出错: {str(e)}', flush=True)
                raise ValueError(f'截图失败: {str(e)}')

if __name__ == '__main__':
    try:
        print('启动温度测试工具...', flush=True)
        root = tb.Window(themename='cosmo')
        app = TemperatureTestApp(root)
        root.mainloop()
    except Exception as e:
        print(f'程序运行出错: {str(e)}', flush=True)
        raise