# Actvero Web 后台

安装和启动见 [项目首页](../README.md)，组件规范见 [界面开发](../docs/UI-DEVELOPMENT.md)。

业务页面位于 `src/features/`，路由位于 `src/routes/`，公共控件与布局位于 `src/components/`。通过 `src/styles/theme.css` 维护统一语义主题。身份页面的 CSS 与 Web 控件由同一构建生成。

常用命令：`pnpm lint`、`pnpm build`、`pnpm test`。后两项中的浏览器测试需要安装 Playwright 浏览器。

上游许可保留于 [LICENSE](LICENSE)，来源见 [upstream.lock.json](../docs/upstream.lock.json)。
