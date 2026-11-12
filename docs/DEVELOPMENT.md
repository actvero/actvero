# 本地开发

准备 Python 3.13、uv、Node.js 24、pnpm 11.25.0 和 Docker Compose。所有依赖按锁文件安装，构建不依赖旁边的个人仓库。

## 启动

```sh
make bootstrap
pnpm build
make infra
make migrate
make install-hooks
```

在两个终端分别运行 `make dev-api` 与 `make dev-web`。默认 Vite 使用 5194，API 使用 5195。不要同时启动占用同样端口与数据项目的完整 Compose。

## 检查

```sh
make check
make test
pnpm --dir frontend exec playwright install chromium --only-shell
pnpm --dir frontend test
make cli-bootstrap cli-check cli-test
python3 scripts/test-identity-theme-assets.py
python3 scripts/test-server.py
python3 scripts/test-server-remote.py
node --test scripts/test-identity-account-switch.mjs
```

后端集成测试需要专用开发 PostgreSQL；测试使用独立 schema。`make test` 从 `ACTVERO_DATABASE_URL` 取得测试连接。直接运行 pytest 时应在 `backend/` 中执行，并明确设置 `ACTVERO_TEST_DATABASE_URL`，避免工作目录影响测试资源路径。依赖真实身份服务的可选测试须使用专用测试 Realm，不能指向真实账号环境。

浏览器测试的截图使用相对于测试文件的 `__screenshots__/` 路径，生成文件由 Git 忽略。不要依赖特定操作系统的绝对临时目录。

抽屉打开或切换后，先确认目标界面可见，再通过共享测试工具 `waitForAnimations` 等待有限动画完成后交互，避免入场动画和焦点恢复与下一次点击竞争。持续加载动画不参与该等待。

API 变更运行 `make generate-api` 并提交生成契约。新迁移保持既有 revision 不变。提交前执行 `make public-check`；本地钩子检查暂存区，CI 重复检查。

## CLI 接口命令

维护专家的 `list`、`show` 和 `update` 命令时，在 FastAPI 管理路由更新接口定义，在 [CLI 命令映射](../cli/scripts/management-commands.json) 维护公开命令名与参数别名。映射使用稳定的 `operationId`。运行 `make generate-api` 生成命令的 HTTP 方法、路径、选项和 JSON 文件的 Schema 名称。`make cli-check` 会核对生成结果，接口仍由平台校验请求内容与组织权限。

增加此类命令时，先确认接口支持 CLI 的组织授权。通用生成支持 UUID 路径参数、字符串或正整数查询参数，以及 JSON 对象请求。写操作复用管理请求编号与回执。涉及二进制上传、轮询或多步发布的命令需要专门处理。更新命令后运行 `make cli-check cli-test`。

## 文档

公开文档遵循 [文档规范](DOCUMENTATION.md)。个人过程材料只放入 `.local/process/` 或仓库外，不写进公共文档目录。
