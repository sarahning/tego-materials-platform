# Tego 部署到 Render

此目录已经改为 Render/Linux Docker 部署方式。

## 架构变化

本地 Windows 版本为了兼容 Python 3.9 和 Hofmann，使用两个 Conda 环境。
Render 运行 Linux，因此 Docker 统一使用 Python 3.11：

- 主网页、CHGNet、ALIGNN、DGL
- Hofmann 三视图
- FastAPI/Uvicorn

全部位于同一个容器、同一个公开 URL 中，不需要在 Render 创建第二个服务。

## 资源要求

- Free / Starter（512 MB）无法容纳 PyTorch、DGL 和三套模型。
- 建议先尝试 Standard（2 GB）。
- 如果日志出现 `Out of memory`、`Killed` 或频繁重启，升级到 Pro（4 GB）。
- 只运行 1 个实例和 1 个 Uvicorn worker。

## GitHub 上传

在当前目录执行：

```powershell
git init
git add .
git commit -m "Deploy Tego materials platform"
git branch -M main
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

数据集文件约 32 MB，低于 GitHub 单文件 100 MB 限制，可以直接提交。不要提交本地 Conda 环境、模型缓存和 runtime 输出。

## Render 创建服务

1. 登录 Render。
2. New -> Web Service。
3. 连接 GitHub 并选择仓库。
4. Runtime 选择 Docker（有 Dockerfile 时通常自动识别）。
5. Root Directory 留空；如果代码放在仓库子目录，则填写该子目录。
6. Instance Type 至少选择 Standard，建议 Pro。
7. Health Check Path 填 `/api/health`。
8. 添加环境变量：

```text
TEGO_PROPERTY_DEVICE=cpu
DGLBACKEND=pytorch
RETRIEVAL_CSVS=/app/mp20_with_jav_dielectric/mp20_with_jav_epsx_epsy_epsz.csv
MPLBACKEND=Agg
```

可选：添加 `OPENAI_API_KEY`，否则自然语言解析会自动使用本地规则。

9. 点击 Create Web Service。

Docker 构建会安装 CPU PyTorch、DGL、CHGNet、ALIGNN 和 Hofmann，并在构建阶段下载两个 ALIGNN 权重。第一次构建可能较慢。

部署成功后，Render 会提供：

```text
https://你的服务名.onrender.com
```

检查：

```text
https://你的服务名.onrender.com/api/health
```

应看到 `ok: true`、`database_ready: true`、`hofmann_available: true`。

## 文件系统说明

Render 默认文件系统是临时的。候选图、Wyckoff 图和性质图在实例重启后消失，但用户重新生成后会恢复。模型权重已烘焙在 Docker 镜像中，不依赖运行时磁盘。

## 常见问题

### 构建时 `No space left on device`

Docker 镜像包含 CPU PyTorch、DGL 和模型，体积较大。清理仓库中的 zip、runtime、模型目录，确认 `.dockerignore` 生效。

### 运行时 `Killed` 或 `Out of memory`

升级实例到 Pro 4 GB，并确认 `--workers 1` 未被修改。

### `database_ready: false`

检查 `RETRIEVAL_CSVS` 是否为：

```text
/app/mp20_with_jav_dielectric/mp20_with_jav_epsx_epsy_epsz.csv
```

并确认 CSV 已提交到 GitHub。

### Hofmann 不可用

查看构建日志中的：

```text
Render dependency check OK
```

若该检查失败，构建会直接停止，不会发布一个缺失三视图的版本。
