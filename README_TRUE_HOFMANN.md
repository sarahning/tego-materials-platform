# Tego 性质预测 + 原版 Hofmann 三视图

这个版本保留已经可运行的 CPU 性质预测，并恢复用户最初网页中的**真实 Hofmann 渲染**。

## 为什么使用双 Python 环境

- 性质预测环境目前是 Python 3.9，包含 CHGNet、ALIGNN、DGL 和 PyTorch。
- 当前 Hofmann 需要 Python 3.11 以上。
- 因此不能把最新版 Hofmann 直接安装进现有 Python 3.9 环境。
- 本项目让性质预测继续使用原环境，并新建一个轻量的 Python 3.13 Hofmann 渲染环境。
- 两个进程只在本机 `127.0.0.1` 通信，前端接口和页面不会显示底层库名称。

这里没有使用 Matplotlib 仿制图。三视图执行的是原版网页中的逻辑：

```python
scene = StructureScene.from_pymatgen(structure, bonds)
scene.view.look_along(direction)
scene.view.zoom = zoom
scene.view.perspective = 0.0
scene.render_mpl(str(output_path))
```

## 第一次安装

先打开 Anaconda PowerShell Prompt，进入项目目录：

```powershell
cd "C:\你的路径\tego_property_prediction_web_true_hofmann"
```

建立专用渲染环境：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_true_hofmann_renderer.ps1
```

它会创建：

```text
conda 环境：tego-hofmann
Python：3.13
依赖：hofmann[pymatgen]、FastAPI、Uvicorn
```

原来的 `website` 环境不会被修改。

## 每次启动

先激活已经能完成性质预测的环境：

```powershell
conda activate website
```

进入项目目录：

```powershell
cd "C:\你的路径\tego_property_prediction_web_true_hofmann"
```

一条命令同时启动真实 Hofmann 服务和主网页：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_windows_cpu_true_hofmann.ps1
```

或双击：

```text
run_windows_cpu_true_hofmann.bat
```

浏览器访问：

```text
http://127.0.0.1:7860
```

## 启动成功标志

终端应显示：

```text
[Tego] Property environment OK
[Tego] Exact Hofmann renderer: READY
[Tego] Open: http://127.0.0.1:7860
```

生成候选后，终端会请求三张图片；页面中应恢复原版的：

- `[100]`
- `[010]`
- `[001]`
- 原子球和按元素着色的键
- 晶胞线框和晶轴标识
- 原版候选卡片列表
- 完整结构与各 Wyckoff group 三视图

## 日志

Hofmann 子服务日志位于：

```text
runtime\hofmann_renderer.stdout.log
runtime\hofmann_renderer.stderr.log
```

若网页正常但图片为空，先查看 `stderr.log`。

## 手动检查 Hofmann 环境

```powershell
conda run -n tego-hofmann python -c "from hofmann import StructureScene, BondSpec; print('Hofmann OK')"
```

检查本地渲染服务：

```powershell
Invoke-RestMethod http://127.0.0.1:7862/health
```

应返回：

```text
ok : True
renderer : hofmann
```

## 目录说明

- `backend/rendering.py`：主服务中的 Hofmann 适配器；不使用仿制渲染。
- `hofmann_renderer_service.py`：在 Python 3.13 中执行原版 Hofmann 代码。
- `install_true_hofmann_renderer.ps1`：创建专用渲染环境。
- `run_windows_cpu_true_hofmann.ps1`：同时启动两个本地服务。
- `backend/property_prediction_engine.py`：现有 CPU 性质预测逻辑。

## 端口

- `7860`：Tego 主网页
- `7862`：本机 Hofmann 渲染子服务

渲染子服务只监听 `127.0.0.1`，不会公开到局域网或公网。
