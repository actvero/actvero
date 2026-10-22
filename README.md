<p align="center">
  <img src="frontend/public/brand/actvero-icon.png" width="96" alt="Actvero" />
</p>

# Actvero

面向团队的 AI 能力管理平台。统一管理模型、MCP 工具、Skills 和专家，让成员通过一致的身份与权限使用团队的 AI 资源。

Actvero 提供 Web 管理后台、模型与工具访问接口，以及桌面客户端接入能力。支持自行部署：社区模式适合一个组织，SaaS 模式支持多个组织和平台运营。

## 可以做什么

- **接入模型**：管理供应商渠道、模型目录、渠道绑定与调用参数，通过统一入口提供对话、向量、重排、图片生成和音频能力。
- **管理工具与技能**：接入 MCP 服务，管理工具、提示词与资源的访问范围；上传、发布和分发有版本的 Skill。
- **配置专家**：把业务指令、Skill 和 MCP 依赖组织为专家，维护草稿、发布版本和成员授权。
- **管理团队访问**：维护组织、成员、邀请、访问密钥和设备会话，按当前成员权限校验资源访问。
- **了解用量**：查看调用记录、执行尝试、用量、额度与结算状态；计量缺失时保留未知或待核对状态。
- **连接桌面端**：通过公开发现、浏览器登录和资源接口，把已授权能力提供给桌面客户端。

模型操作的实际可用范围取决于供应商、模型、渠道绑定和管理员配置。不同接口支持的参数与媒体格式见对应文档。

## 平台与桌面端

平台负责团队资源的配置、授权、版本分发和用量记录。Actvero 桌面端负责本地工作区、会话与任务执行，两者分别维护。

```text
管理员 ── Web 控制台 ── Actvero 平台
                            │
             ┌──────────────┼──────────────┐
             │              │              │
          模型渠道       MCP 服务      专家与 Skills
             │              │              │
             └────────── 授权访问 ──────────┘
                            │
                      桌面端 / API 客户端
```

本仓库包含平台、Web 后台、身份主题和管理 CLI。桌面应用的安装与使用说明由桌面项目维护。

## 快速开始

准备 Git、Docker Engine 或 Docker Desktop，以及 Docker Compose 2.24.4 或更新版本。

```bash
git clone https://github.com/actvero/actvero.git
cd actvero
sh scripts/docker-env.sh
docker compose up --build -d --wait --wait-timeout 240
```

打开 **http://127.0.0.1:5194/console**，按页面引导创建组织与首位管理员，然后登录控制台。

启动脚本会生成独立随机凭据并保存在被 Git 忽略的 `.env` 中，已有文件不会被覆盖。首次构建需要下载依赖。应用、PostgreSQL、Keycloak 和开发邮件服务由 Compose 一起启动；数据库迁移服务成功退出属于正常状态。

这套默认配置用于本地体验。公网部署、HTTPS、正式邮件、备份和升级见 [部署说明](docs/DEPLOYMENT.md) 与 [服务器部署](docs/SERVER-DEPLOYMENT.md)。

```bash
docker compose ps -a                 # 查看服务状态
docker compose logs --tail 100 app   # 查看应用日志
docker compose down                 # 停止服务，保留数据卷
```

## 部署模式

| 模式 | 使用场景 | 配置 |
| --- | --- | --- |
| Community | 团队独立部署，一个实例一个组织 | 默认 `ACTVERO_PLATFORM_EDITION=community` |
| SaaS | 同一平台服务多个组织，提供组织开通与平台运营 | 新实例初始化前设置 `ACTVERO_PLATFORM_EDITION=saas` |

两种模式的代码都在本仓库。平台运营权限与组织资源权限分别校验。SaaS 的初始化流程见 [平台开通说明](docs/PLATFORM-ONBOARDING.md)；已有实例的模式变更不能代替数据与权限迁移。

## 项目结构

```text
backend/       FastAPI 应用、数据库迁移和后端测试
frontend/      React 管理后台、业务页面和共享组件
identity/      Keycloak 初始配置、登录与邮件主题
cli/           独立安装的管理 CLI
agent-skills/  管理 CLI 配套 Skill
deploy/        Docker 镜像、Compose 和反向代理配置
scripts/       环境、构建、迁移、运维与验证工具
docs/          使用文档、架构和接口契约
```

后端使用 Python、FastAPI、SQLAlchemy、PostgreSQL 和 Alembic；前端使用 React、TypeScript、Vite、shadcn/Radix、Tailwind CSS 和 TanStack。身份认证由 Keycloak 提供，模型适配复用 LiteLLM SDK，MCP 集成复用 FastMCP。具体版本以锁文件和 Dockerfile 为准。

## 本地开发

准备 Python 3.13、uv、Node.js 24、pnpm 11.25.0 和 Docker Compose。在未运行上述完整应用容器的环境中执行：

```bash
make bootstrap
pnpm build
make infra
make migrate
```

然后在两个终端分别运行：

```bash
make dev-api
```

```bash
make dev-web
```

API 或数据结构变更后，同步生成契约并运行相关检查：

```bash
make generate-api
make check
make test
pnpm --dir frontend exec playwright install chromium --only-shell
pnpm --dir frontend test
```

后端集成测试使用独立测试 schema；运行测试前需要可用的开发 PostgreSQL。前端和身份主题共享构建来源。详细开发说明见 [贡献指南](CONTRIBUTING.md)。

管理 CLI 通过 npm 独立安装，支持登录、组织发现、渠道只读查询，以及 Skills、MCP 和专家维护。平台须启用管理接口；兼容性检查和写权限授权见 [CLI 接入说明](docs/CLI.md)。

## 文档

- [文档导航](docs/README.md) · [架构](docs/ARCHITECTURE.md) · [配置](docs/CONFIGURATION.md)
- [模型渠道](docs/MODEL-CHANNELS.md) · [模型管理](docs/MODEL-CATALOG.md) · [额度策略](docs/QUOTA-POLICIES.md)
- [专家](docs/EXPERTS.md) · [Skills](docs/SKILLS-WORKBENCH.md) · [MCP](docs/MCP-WORKBENCH.md)
- [桌面接入](docs/DESKTOP-ACCESS.md) · [OpenAPI](docs/api/openapi.json)

## 贡献

欢迎通过 Issue 报告可复现的问题、讨论需求，或提交聚焦单一问题的 Pull Request。开发约定和验证要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 中的私密报告方式提交。

## 许可证与致谢

Actvero 的项目代码采用 [MIT License](LICENSE)。第三方源码与素材保留各自的许可证和版权声明，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。

感谢 [Shadcn Admin](https://github.com/satnaing/shadcn-admin)、[shadcn/ui](https://ui.shadcn.com/)、[LiteLLM](https://github.com/BerriAI/litellm)、[FastMCP](https://github.com/PrefectHQ/fastmcp) 和 [Keycloak](https://www.keycloak.org/) 等项目。
