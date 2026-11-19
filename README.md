# 《日报》全自动深度资讯生成与阅读系统

基于 **GitHub Actions + DeepSeek-V3 + GitHub Pages / Cloudflare Pages** 的全自动、零成本无服务器深度资讯系统。

- **定时触发**：每天北京时间凌晨 **02:00**（UTC 18:00）全自动运行。
- **信源抓取**：多节点抓取微博热搜、知乎热榜、央视要闻、人民网社会、小黑盒等实时热门切面。
- **AI 深度重构**：DeepSeek 按照严格排版规范生成 15 篇跨领域深度长文（社会热点、科技产业、历史纵深、设计与文化、游戏机制）。
- **静态归档**：增量提交至 `data/articles.json`，保留最近 300 篇深度长文。
- **前端直连**：前端单页应用内置「云端信源拉取」引擎与离线阅读模式。

---

## 快速部署指南

### 第一步：创建 GitHub 仓库并上传代码

在当前文件夹下初始化 Git 仓库并推送到你的 GitHub：

```bash
git init
git add .
git commit -m "feat: init ribao auto-fetch pipeline"
git branch -M main
git remote add origin https://github.com/你的GitHub用户名/你的仓库名.git
git push -u origin main
```

### 第二步：配置 GitHub Actions Secrets

进入 GitHub 仓库页面：
1. 点击顶部 **Settings** -> 左侧 **Secrets and variables** -> **Actions**。
2. 点击 **New repository secret**，添加以下密钥：
   - `LLM_API_KEY`: 填入你的 DeepSeek API Key（例如 `sk-9938bd4276d64fba9d2ee59096f32c03`）
   - `LLM_BASE_URL`: `https://api.deepseek.com`
   - `LLM_MODEL`: `deepseek-chat`
3. 确保 Actions 有代码写入权限：
   - 同样在 **Settings** -> **Actions** -> **General**。
   - 滚动到底部的 **Workflow permissions**，选择 **Read and write permissions**，点击保存。

### 第三步：手动触发测试

1. 点击仓库顶部的 **Actions** 标签页。
2. 在左侧选择 **Auto Fetch & Generate Ribao News**。
3. 点击右侧的 **Run workflow** -> 绿色按钮 **Run workflow**。
4. 约 40~60 秒运行完毕变绿后，仓库中的 `data/articles.json` 将自动被更新！

### 第四步：启用一键网页托管（GitHub Pages）

1. 进入仓库 **Settings** -> 左侧 **Pages**。
2. **Build and deployment** 下的 **Source** 选择 **Deploy from a branch**。
3. Branch 选择 `main`，文件夹选择 `/ (root)`，点击 **Save**。
4. 稍等 1 分钟即可得到你的专属在线《日报》地址：
   `https://<你的GitHub用户名>.github.io/<你的仓库名>/`
   - 打开网页，点击右上角「**云端**」按钮，即可看到每日凌晨 02:00 自动更新的最新报道！

---

## 文件结构说明

```
├── .github/
│   └── workflows/
│       └── daily_news.yml       # GitHub Actions 定时任务配置（每天凌晨02:00自动运行）
├── data/
│   └── articles.json            # 增量深度长文数据池
├── fetch_and_generate.py        # 抓取与 DeepSeek 深度撰写脚本
├── index.html                   # 《日报》PWA 沉浸式阅读器前端
├── requirements.txt             # Python 依赖清单
└── README.md                    # 本文档
```
