# OpenRSI Local Research

在自己的机器上把研究想法变成可运行的实验：**提案 → 独立评审 → 构建 Harbor 任务 → 正负对照验收 → RSI-Harness 运行**。本地工作流不提交 GitHub Discussion，不依赖原版的私有任务构建服务，也不上传实验轨迹。

## 从一个想法开始

用 Codex 或你常用的代码 Agent 打开**这个 checkout**。每一阶段按下面的 Prompt 新开一个对话。把 `<实验目录>` 换成同一个实际路径；建议把实验放在 checkout 外，免得误提交。

### 1. 提案

```text
请定位这个 OpenRSI Local Research checkout，阅读 local-research/PROMPTS.md 的「1. 提案」和 local-research/README.md。按本地提案流程引导我，把研究想法写成 <实验目录>/proposal.toml。先问我想验证什么；不提交远端，不执行实验。
```

### 2. 独立评审

提案写好后，另开一个对话，不带提案对话历史：

```text
请定位这个 OpenRSI Local Research checkout，阅读 local-research/PROMPTS.md 的「2. 独立评审」。独立评审 <实验目录>/proposal.toml，将结论和理由写到 <实验目录>/review-notes.md。不要改提案，也不要替我批准；等我确认，再记录决定。
```

### 3. 构建与验收

确定通过后，再开一个对话：

```text
请定位这个 OpenRSI Local Research checkout，阅读 local-research/PROMPTS.md 的「3. 构建与验收」。先确认 <实验目录> 存在对当前提案的批准，再按简报构建 Harbor 任务，打包并用 RSI-Harness 验证正负对照。报告实测结果；不要发布，也不要启动正式研究。
```

### 4. 正式运行

两个对照都通过后，再执行：

```sh
uv run --project RSI-Harness python local-research/research.py run '<实验目录>' --agent codex
```

优化 Agent 由 Harness 启动，不用另开对话。CPU 示例、Docker 和模型配置、GPU 参数以及实验产物位置都在[完整操作指南](local-research/README.md)。如果你自己做评审，可以跳过第二个对话，但仍需用指南中的命令记录决定。

## 仓库结构

- [`local-research/`](local-research/README.md)：本地命令、对话 Prompt、CPU 示例和测试。
- [`RSI-Harness/`](RSI-Harness/)：保留原评测引擎，负责容器、Agent、提交、评分和结果。
- 原公开题库、投稿和发布流程留在[上游 OpenRSI Index](https://github.com/OpenRSI-Foundation/OpenRSI-Index)，不放在这个分支。你的实验和运行记录留在各自的本地目录。

本 fork 的 `main` 跟踪官方上游；请在 `local-research` 分支使用本地版。升级引擎时先比较上游的 `RSI-Harness/` 改动，再选择同步和验收，不把原投稿流程合回来。
