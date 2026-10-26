# 系统架构

Actvero 由 Web 控制台、FastAPI 业务应用、PostgreSQL、Keycloak 和独立管理 CLI 组成。构建后的 Web 资源由应用托管；桌面应用通过版本化接口接入。

## 边界

Keycloak 负责认证协议、密码与 MFA。平台负责组织成员关系、资源权限、设备会话、专家/Skill 版本、额度、结算与审计。平台运营与组织管理员是不同权限边界。

模型适配、路由及上游执行复用 LiteLLM SDK；MCP 集成复用 FastMCP。调用证据与计量状态由平台保存。缺失计量不得补零，响应交付不等同于已确认结算。

## 代码组织

后端按 `backend/app/modules/` 下的业务域组织；前端按 `frontend/src/features/` 组织页面，`routes/` 仅负责接入。API 的机器可读定义是 [OpenAPI](api/openapi.json)，前端类型由它生成。

历史迁移文件共同构成当前数据库初始化和升级链，不能为了精简仓库而移除。使用 `alembic heads` 获取实际目标版本。

## 数据与外部访问

业务和身份数据分别存储；会话和上游凭据使用持久加密配置。公网模型与 MCP 请求采用各自的网络策略，内网访问需要明确配置。头像、Skill 包等业务资产与运行中的账务 outbox 需要纳入备份。

## 参考

[文档导航](README.md) · [API 契约](api/openapi.json)

## 客户端分发

`client_distribution` 扩展既有客户端版本表，维护加密存储配置、文件、multipart 上传、持久化校验任务、发布计划与更新通道快照。Web 与 CLI 使用不同认证入口并复用领域服务；公开更新清单仅引用校验后的发布文件。操作契约见[客户端更新发布](CLIENT-DISTRIBUTION.md)。
