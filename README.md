# 璇玑 Tego：晶体设计与性质预测平台

本版本在原有“目标性质设置 → 候选结构生成 → 结构/性质/Wyckoff 分析”流程中，新增了独立的 **晶体性质预测工作台**。

## 新增能力

- 候选结构卡片新增“性质预测”按钮。
- 晶体微观结构页面新增“预测当前结构性质”入口。
- 顶部导航新增独立“性质预测”页面。
- 支持三种结构来源：
  - 当前生成的候选晶体；
  - 本地 `.cif` 文件；
  - 直接粘贴完整 CIF 文本。
- 输出三项快速预测结果：
  - 局域绝对磁矩密度，单位 `μB/Å³`；
  - 带隙，单位 `eV`；
  - 最大静态介电常数。
- 同时显示结构预览、晶胞参数、逐位点磁矩和结果说明。
- 计算引擎采用懒加载：网页启动时不会立即占用大量内存；第一次预测时加载一次，之后持续复用。
- 前端统一显示为 `Tego Property Intelligence`，不展示底层权重或外部模型名称。

## 目录说明

```text
backend/
  main.py                         FastAPI 主后端与性质预测接口
  property_prediction_engine.py  三项性质的内部推理封装
  property_prediction_service.py 懒加载、结果产品化与状态管理
frontend/
  index.html                      新增性质预测页面
  app.js                          新增候选跳转、上传 CIF 与预测交互
  styles.css                      新增工业风性质预测工作台样式
run_windows_cpu.ps1               Windows CPU 启动脚本
install_property_cpu_windows.ps1  Windows CPU 依赖安装脚本
download_property_models.py       预下载并验证模型
verify_property_platform.py       环境与接口检查
```

# 一、在你现有的 website 环境中运行

你已经完成 CPU 推理环境配置时，不要重新创建环境。直接执行：

```powershell
conda activate website

cd "C:\Users\Lenovo\Desktop\1.15任务成果保存\mattergen-main\tego_property_prediction_web"

$env:DGLBACKEND="pytorch"
$env:TEGO_PROPERTY_DEVICE="cpu"

python verify_property_platform.py
```

检查通过后，预加载模型：

```powershell
python download_property_models.py
```

你之前下载的模型位于用户缓存目录时，会直接复用，不会重复下载。

启动网页：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_windows_cpu.ps1
```

或双击：

```text
run_windows_cpu.bat
```

浏览器访问：

```text
http://127.0.0.1:7860
```

# 二、当前环境缺少依赖时

确保已经进入 `website` 环境：

```powershell
conda activate website
```

然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_property_cpu_windows.ps1
```

该脚本采用以下核心组合：

```text
Python      3.9
PyTorch     2.2.1 CPU
DGL         2.2.1 CPU
TorchData   0.7.1
NumPy       1.26.4
CHGNet包    0.3.8
ALIGNN      2026.5.20
```

安装完成后再次运行：

```powershell
python verify_property_platform.py
python download_property_models.py
```

# 三、使用性质预测页面

## 方式 1：预测生成的候选结构

1. 在“设计入口”生成候选结构。
2. 在候选卡片中点击“性质预测”。
3. 页面会自动载入对应 CIF，并开始预测。

也可以进入“晶体微观结构”后，点击右上角：

```text
预测当前结构性质
```

## 方式 2：上传本地 CIF

1. 顶部导航点击“性质预测”。
2. 点击“载入 CIF 文件”。
3. 选择本地 `.cif` 文件。
4. 点击“开始性质预测”。

## 方式 3：粘贴 CIF

1. 顶部导航点击“性质预测”。
2. 将完整 CIF 粘贴到文本框。
3. 点击“开始性质预测”。

# 四、接口

## 状态接口

```text
GET /api/property-predictor/status
```

## 任意 CIF 预测

```text
POST /api/property-predictor/predict
```

请求：

```json
{
  "source_name": "sample.cif",
  "cif": "完整 CIF 文本"
}
```

## 已生成候选结构预测

```text
POST /api/candidates/{candidate_id}/predict-properties
```

# 五、重要说明

1. 磁性页面显示的是**局域绝对磁矩密度**：

```text
所有位点磁矩大小之和 / 当前晶胞体积
```

它不等同于考虑自旋正负抵消后的净磁矩密度，因此不能直接据此判断反铁磁材料的净磁化强度。

2. 输入结构不会自动弛豫。预测结果对应当前 CIF 中的晶格和原子坐标。

3. 带隙与介电常数适合用于快速筛选和排序。重要候选仍建议进行更高精度计算或实验验证。

4. 启动时请保持：

```text
--workers 1
```

多个 Worker 会分别加载一套计算引擎，显著增加内存占用。

5. CPU 第一次预测会包含模型加载时间。完成第一次预测后，后续预测会直接复用已加载模型。
