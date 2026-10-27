# 安装与升级

默认 Compose 面向本机体验，公网部署使用 [服务器部署](SERVER-DEPLOYMENT.md)。准备 Git、Docker 和 Compose 2.24.4+。

## 首次启动

```sh
git clone https://github.com/actvero/actvero.git
cd actvero
sh scripts/docker-env.sh
docker compose up --build -d --wait --wait-timeout 240
```

环境生成器创建随机凭据和权限受限的 `.env`，已有文件保持不变。默认社区模式，访问 http://127.0.0.1:5194/console 初始化组织与首位管理员。SaaS 模式在首次启动前设置 `ACTVERO_PLATFORM_EDITION=saas`，按 [开通说明](PLATFORM-ONBOARDING.md) 初始化。

| 服务 | 默认本机入口 | 用途 |
| --- | --- | --- |
| app | 5194 | Web 与 API |
| postgres | 5494 | 业务库和身份库 |
| keycloak | 5196 | 身份服务 |
| mailpit | 5198 / SMTP 5197 | 开发邮件捕获 |
| migrate | 无 | 迁移完成后退出 0 |

所有默认宿主端口仅监听回环地址。APP_URL、issuer 与浏览器地址必须一致，localhost 与 127.0.0.1 不混用。Mailpit 不替代正式邮件服务。

## 查看与停止

```sh
docker compose ps -a
docker compose logs --tail 100 app migrate keycloak
curl --fail http://127.0.0.1:5194/api/v1/ready
docker compose down
```

停止时保留数据卷，不使用 `down -v`。自定义 `.env`、项目名或同源覆盖文件必须在后续每次命令中保持一致。

## 已有实例升级

先停止业务写入，备份业务库、身份库、私有环境配置和加密密钥，以及持久 `llm-outbox` 数据。确认归档可读，保留原提交和镜像。备份可读取不代表恢复演练已完成。

在干净源码目录快进至目标版本，然后重新构建、迁移和启动：

```sh
git pull --ff-only
docker compose build
docker compose run --rm migrate
docker compose up -d --wait --wait-timeout 240
docker compose exec app alembic current
```

迁移失败时保留错误与备份，不清库重试。目标版本由当前源码 `alembic heads` 确定。回退代码不能自动回退数据库，需要兼容代码或已验证的成套恢复。

Realm 模板只导入空身份库，修改模板不会自动更新已有账号和客户端。更换 issuer、回调、客户端秘密或运行拓扑需按相应身份流程处理。

## 模型网关

新配置默认随 Compose 启动兼容 New API，凭据自动初始化，网关数据保存在独立卷中。多个组织共用实例，各自维护渠道、模型和价格。分开部署时清空 `COMPOSE_PROFILES`，设置 `ACTVERO_NEWAPI_BASE_URL` 和 `ACTVERO_NEWAPI_MANAGEMENT_TOKEN`，再启动 Actvero；不会启动或停止外部网关。已有配置不会自动接管原有网关数据。版本、网络设置、旧数据归属及备份步骤见 [网关部署说明](../integrations/newapi/README.md)。
