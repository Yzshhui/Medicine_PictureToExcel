# 药品包装/发票识别工具

将药品包装盒或发票图片批量识别为结构化 Excel，支持药名、厂家、国药准字、规格四字段提取。

## 功能特性

- 双模式识别
  - 本地 EasyOCR：无需联网，适合清晰包装盒文字
  - AI 视觉 API（OpenAI 兼容）：支持模糊/复杂布局/发票，准确率更高
- 智能解析：自动从 OCR 文本或 AI 返回中提取 4 字段，容错别名映射
- 国药准字验证：集成万维易源 ShowAPI (1468-4) 官方药品数据库校验
- 可编辑表格：识别结果在界面直接修改，支持行级警告标红
- Excel 导出：一键导出带表头、自动列宽、警告行高亮
- 配置持久化：API Key、模型、工作目录、模型目录自动记忆
- 模型下拉管理：推荐模型 + 历史记忆，右键删除条目，可恢复默认
- ShowAPI 账号下拉：AppKey + Secret 配对记忆，选择自动填充 Secret，右键删除账号

## 快速开始

pip install -r requirements.txt
python main.py
# 或双击 start.bat

## 依赖

openai>=1.0.0
easyocr>=1.7.0
torch torchvision
opencv-python
Pillow
openpyxl
numpy

## 配置说明 (config.json)

base_url: OpenAI 兼容 API 地址（如 SiliconFlow: https://api.siliconflow.cn/v1）
api_key: API 密钥
model: 视觉模型名称（必须支持图像输入，如 Qwen/Qwen2.5-VL-72B-Instruct）
work_dir: 默认图片选择目录
model_dir: EasyOCR 模型存放目录（首次运行自动下载 ~50MB）
output_dir: Excel 导出默认目录
model_history: 用户使用过的模型历史（下拉记忆）
model_removed: 用户右键删除的推荐模型
showapi_appkey: 万维易源 AppKey（药品验证）
showapi_secret: 万维易源 Secret
showapi_base: API 基址（默认 https://route.showapi.com）
showapi_enabled: 是否启用药品验证

## 推荐模型 (SiliconFlow)

Qwen/Qwen2.5-VL-72B-Instruct: 强推，视觉能力强，中文理解好
Qwen/Qwen-VL-Plus: 速度较快，准确度良
gpt-4o: OpenAI 官方，需海外网络

注意：纯文本模型（如 Qwen3.5-9B、deepseek-v3）无视觉能力，不可用于图片识别。

## 使用流程

1. 点击 设置 填入 API Key、选择模型
2. 点击 测试连接 验证
3. 点击 添加图片 导入药品包装/发票图片
4. 选择识别模式：
   - 本地 OCR：离线、快速、适合清晰包装盒
   - AI 视觉：联网、准确、适合发票/模糊图/复杂布局
5. 结果在右侧表格可直接编辑（红字行有警告）
6. 点击 导出 Excel 保存

## ShowAPI 药品验证

- 接口：万维易源 1468-4 药名查询药品信息
- 免费额度：每日 ~100 次，足够日常使用
- 自动对比识别结果与官方数据库，不匹配标红提示

## 目录结构

Project-002-medicine-excel/
main.py
medicine_ocr.py
showapi_client.py
config.json
start.bat
README.md

## 常见问题

Q: 识别结果为空？
A: 检查模型是否为视觉模型（必须含 VL/Vision）；图片是否过模糊/倾斜/文字过小；尝试切换 AI 视觉模式

Q: EasyOCR 首次运行卡住？
A: 首次需下载模型 (~50MB)，请耐心等待或检查网络。

Q: 国药准字格式错误？
A: 标准格式：国药准字H/Z/S/B/J + 8位数字，程序会自动校验并警告。

Q: 如何删除下拉列表里的模型？
A: 模型下拉框右键 -> 选择删除：xxx -> 自动持久化，下次不再显示。可点恢复默认列表找回。

## 许可

MIT License
