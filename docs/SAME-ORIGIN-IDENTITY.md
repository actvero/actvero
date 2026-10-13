# 同源身份部署

同源拓扑将应用和 Keycloak 放在同一可信站点下，身份路径为 `/identity`。`deploy/same-origin.compose.yaml`、服务器覆盖与代理模板共同定义入口。

## 配置一致性

外部应用地址、issuer、回调、代理路径与 Keycloak hostname 必须匹配。容器内部地址与浏览器地址分别配置，不把容器回环地址暴露给浏览器。

## 已有身份迁移

改变 issuer 会影响 `issuer + subject` 映射，不能靠新邮箱匹配接管旧身份。使用专门迁移工具前先阅读 `scripts/migrate-identity-issuer.py --help`，备份业务和身份数据，并在隔离环境验证映射。

## 运行

同源实例启动、停止和升级始终带齐相同的 Compose 文件，不能误用只有根 compose 的命令切回不同拓扑。生产入口需要可信 HTTPS、正确的回调与代理配置。

## 参考

[文档导航](README.md) · [API 契约](api/openapi.json)
