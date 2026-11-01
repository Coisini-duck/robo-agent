# robo-agent

面向 **嵌入式 / ROS 2 / VLA 部署** 的 Hermes Agent 发行版。
把日常那套工程习惯、技能和交付规范打成一个可安装的 agent。

## 安装

```bash
# 从 GitHub 安装
hermes profile install github.com/coisini-duck/robo-agent --alias

# 或者本地目录（还没推上去时）
hermes profile install <本地路径>/robo-agent --alias
```

然后填自己的 key：
```bash
cp .env.EXAMPLE .env    # 或直接 hermes -p robo-agent setup
```

## 带什么

- `SOUL.md` —— 工程纪律：证据优先、先审计后建议、可逆优先、失败要如实报
- `config.yaml` —— 模型与工具默认值（不含任何密钥、不含本机路径）
- `skills/`（11 个）：
  - ros2-development
  - stm32-keil-proteus
  - systematic-debugging
  - github
  - docusaurus-docs-site
  - docx
  - xlsx
  - pdf
  - xmind
  - local-llm-windows-gpu
  - hermes-agent

## 不带什么

密钥、记忆、会话历史、cron 任务、MCP 本机路径 —— 一律不进发行版，装完自己配。

## 更新

```bash
hermes profile update robo-agent
```
