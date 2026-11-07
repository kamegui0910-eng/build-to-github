# Build to GitHub

## 中文

**你提供：**想做的产品、使用场景、已有代码，以及需要的界面或运行方式。

**AI 帮你做：**整理需求，复用已有能力，搭建可运行应用，测试修复，再按你的要求打包、迁移或发布到 GitHub。它也会留下简短的项目状态，方便下次接着做。

这是开发方法 skill，适用于不同平台。它不包含课程系统、模型权重、API 密钥或已登录账号。

**怎样用：**

```text
$skill-installer Install skills/build-to-github from https://github.com/kamegui0910-eng/build-to-github
```

安装后告诉 AI：

```text
使用 $build-to-github。我想做一个……平台。用户提供……，希望得到……。
已有项目在……，最后要做成……，并发布到我的 GitHub。
```

也可下载仓库，把 `skills/build-to-github` 整个文件夹放入所用工具的 skills 目录。Codex 通常使用 `~/.codex/skills/`；需要重新发现 skill 时重启会话。其他工具的安装位置以各自说明为准。

[Skill 正文](skills/build-to-github/SKILL.md) · [实际案例](skills/build-to-github/references/campus-example.md)

## English

**You provide:** A product idea, its users, existing code, and the interface or runtime you want.

**AI helps you:** Define the requirements, reuse existing capabilities, build and test a working app, then package, migrate, or publish it to GitHub as requested. It keeps a short project state for the next development session.

This is a reusable development skill. It contains no coursework app, model weights, API keys, or signed-in accounts.

Install with the command above, or copy `skills/build-to-github` into your tool's skills directory. Then ask: “Use $build-to-github to build this product: … Users provide … and receive … Deploy/package it as … and publish it to my GitHub.”

Publishing, deployment, and paid API calls use your own tools, accounts, and task authorization. References load only when needed; token savings have not been measured.
