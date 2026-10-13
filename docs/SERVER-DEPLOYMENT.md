# 服务器部署与维护

服务器脚本组合应用、同源身份和生产覆盖文件。准备 Python 3、Docker Compose 2.24.4+、可信 HTTPS 入口和可用磁盘。反向代理与证书由部署者配置。

## 新实例

```sh
python3 scripts/server.py configure \
  --url https://actvero.example.com \
  --project actvero-server --port 5194 \
  --data-dir "$HOME/data/actvero" \
  --backup-dir "$HOME/backups/actvero"
make server-up
make server-check
```

生成的 `.env.server` 被忽略，已有文件不会覆盖。此配置采用 SaaS 与同源 `/identity` 入口；只有边缘服务绑定回环端口。部署者通过站点初始化运营身份和组织，不存在通用业务管理员密码。

正式邮件需要配置真实 SMTP。公开 HTTPS、OIDC issuer、回调和匿名拒绝检查之外，还应完成真实身份登录验证。

## 远程升级

在有仓库读取权限、Docker 和 SSH 的操作电脑执行：

```sh
make server-upgrade HOST=deployment-host REMOTE_PATH=/srv/actvero
```

`HOST` 是已配置的 SSH 别名，路径必须显式提供。脚本读取已提交的 main，按固定提交构建 linux/amd64 镜像，传输并核对版本，再进行服务器快进、备份、迁移和健康检查。宿主 Docker 需支持按平台导出镜像。

服务器已有合法读取权限时，可在服务器源码目录执行 `make server-upgrade`；也可使用 `BUNDLE=/absolute/main.bundle`。仅接受可快进历史，脏目录或分叉历史会停止，不使用强制重置。

## 数据保护

升级在停止写入后成套备份业务库、身份库、环境及账务 outbox。失败时停止在相应阶段；不自动清库或覆盖恢复。保留原加密密钥与身份配置。

账务 outbox 位于应用 `/app/data/llm-outbox` 的持久卷中，恢复时与同一备份的业务/身份库配套。其重放处理账务证据，不重新调用模型。不要删除未知费用对应文件来消除异常。

## 运行命令

```sh
make server-status
make server-logs
make server-check
make server-stop
```

这些命令保留同一组 Compose 覆盖。不要用仅根 compose 的命令切换拓扑。多 worker 运行还需要验证共享冷却、状态和额度行为，不能以单进程健康检查代替。
