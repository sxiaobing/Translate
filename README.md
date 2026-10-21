# 截图翻译（Windows）

这是一个单次截图翻译桌面应用：用户框选屏幕区域，应用使用 PaddleOCR 识别其中的文字，再通过 DeepSeek Chat Completions 将识别结果翻译成指定语言。截图只发送给本地 OCR，不会发送给 DeepSeek；DeepSeek 接口只接收 OCR 得到的纯文本。

## 环境要求

- Windows 10/11
- Python 3.11 或 3.12（建议使用 64 位版本）
- 可访问 DeepSeek API 的网络

项目在 Windows 上固定使用 `paddlepaddle==2.6.2`，以避免 PaddlePaddle 3.x 与 PaddleOCR 2.x 在部分 CPU 环境中的 OneDNN 推理错误。`requirements.txt` 已包含该版本约束。

## 安装

在项目目录打开 PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果使用 Python 3.12，把第一行的 `-3.11` 改为 `-3.12`。首次运行 PaddleOCR 可能会自动下载 OCR 模型，请保持网络畅通。

## 配置 API Key

临时配置（只对当前 PowerShell 窗口有效）：

```powershell
$env:DEEPSEEK_API_KEY = "sk-你的密钥"
```

永久配置（执行后请重新打开终端）：

```powershell
setx DEEPSEEK_API_KEY "sk-你的密钥"
```

应用只从环境变量 `DEEPSEEK_API_KEY` 读取密钥，不会把密钥写入代码、截图、日志或仓库。不要把真实密钥提交到 Git。

## 运行

```powershell
python main.py
```

点击“框选并翻译”，主窗口会最小化。拖动鼠标框选文字区域，松开鼠标后等待 OCR 和翻译完成；按 `Esc` 可取消。选择目标语言后，识别原文和翻译结果会分别显示在两个文本区，点击“复制译文”可复制结果。

## 常见问题

- **提示未配置 API Key**：在启动应用的同一个 PowerShell 会话中设置 `DEEPSEEK_API_KEY`，或重新打开终端使 `setx` 生效。
- **401**：密钥无效、过期或复制时包含多余字符，请到 DeepSeek 控制台检查。
- **超时或无法连接**：检查网络、防火墙和代理；应用会把网络错误显示在翻译结果区。
- **未识别到文字**：选择更大的区域、提高文字清晰度，避免只框到背景或遮挡文字。
- **PaddleOCR 安装失败**：确认 Python 为 3.11/3.12 64 位，并按 PaddlePaddle 官方 Windows 安装说明选择匹配的 wheel。
- **`OneDnnContext does not have the input Filter`**：确认已使用项目目录内的虚拟环境，并重新安装锁定版本：`python -m pip install --force-reinstall "paddlepaddle==2.6.2"`，然后完全退出并重新启动应用。
- **按 Esc 后窗口没有恢复**：等待当前系统事件处理完成，再重新点击“框选并翻译”；应用不会启动连续截图任务。

## 速度优化

- 应用启动后会在后台预热 PaddleOCR，避免第一次框选时再等待模型加载。
- 默认跳过文字方向分类，适合常见的横排屏幕文字。需要识别竖排或倒置文字时，可在启动前设置 `$env:SCREEN_TRANSLATOR_OCR_ANGLE = "1"`。
- 翻译采用流式输出，识别完成会立即显示原文，译文收到一部分就展示一部分。
- DeepSeek 连接会复用，连续多次翻译时少一次 TLS 建连开销。网络本身的首字延迟仍取决于到 API 服务和代理的线路。
- 框选范围越小，OCR 需要处理的文字行越少，速度越快；应用会自动尝试 MSS 截图，失败时改用 Qt 截图。

## 文件结构

- `main.py`：程序入口
- `ui.py`：主窗口和后台工作线程
- `capture.py`：透明框选遮罩和 mss 截图
- `ocr.py`：PaddleOCR 调用及阅读顺序整理
- `translator.py`：DeepSeek 文本翻译请求
- `config.py`：接口配置和环境变量读取

## 打包为 Windows exe

项目使用 PyInstaller 的目录模式（`onedir`）。PaddlePaddle 会加载多个 DLL、模型文件和 OCR 资源，不适合只分发一个单文件 exe。

先确认本机已经成功运行过一次 OCR，使 PP-OCRv4 模型缓存在：

```text
%USERPROFILE%\.paddleocr\whl
```

然后在项目根目录执行：

```powershell
.\build.ps1
```

生成文件：

```text
dist\ScreenTranslator\ScreenTranslator.exe
dist\ScreenTranslator\models\paddleocr\whl\...
```

发布时必须把整个 `dist\ScreenTranslator` 文件夹压缩后交付，不能只发 `ScreenTranslator.exe`。目标电脑不需要安装 Python，也不需要自己下载 OCR 模型。

模型文件会随程序分发；如果模型缓存缺失，先联网运行一次 `main.py` 完成下载。已经安装 PyInstaller 且模型齐全时，可以加 `-SkipInstall` 跳过安装步骤：

```powershell
.\build.ps1 -SkipInstall
```

打包后的 API Key 仍通过环境变量读取，不会写入 exe：

```powershell
setx DEEPSEEK_API_KEY "sk-你的密钥"
```

目标电脑需要重新打开终端或重启资源管理器相关会话，`setx` 才会对新启动的程序生效。
