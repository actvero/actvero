# 客户端更新发布

平台运营在“客户端版本”统一管理构建文件、网站下载安装与客户端更新通道，对象存储独立位于“设置 → 对象存储”。此功能属于 SaaS 平台运营权限，与组织资源管理分开。历史下载记录仍在版本列表中，历史草稿保存资料后可接入更新发布，已发布记录保留下载和下架。

## 准备存储

填写 S3 HTTPS endpoint、区域、Bucket 和文件前缀，选择默认存储。公共下载根地址可留空，使用私有桶签名读取；配置公共 CDN 时可填写该地址。公共根地址应指向桶或 CDN 的根路径，系统会追加文件前缀与唯一对象路径。访问密钥使用平台会话加密密钥加密保存，查询接口不返回密钥。轮换密钥可编辑原配置；已有文件的 endpoint、Bucket、区域、前缀和公共地址不可原地修改，迁移存储请新增配置。

“测试连接”会创建临时对象，检查写入、读取、单段 Range 和删除。供应商、桶权限与 CDN 配置需要在实际环境验证；S3 兼容不表示所有供应商配置都已通过验证。公共读取应保持原始字节，不自动压缩安装包。配置桶生命周期，清理超过 7 天的未完成 multipart 上传。不要按文件年龄自动删除已发布对象。

浏览器通过同源 API 转发 16 MiB 分片，不需要为浏览器开放桶 CORS；反向代理需允许至少 16 MiB 的请求体及足够上传时间。CLI 使用有效期 15 分钟的签名地址直传，平台凭据不会发给存储服务。上传任务有效期 7 天，归发起用户所有。存储配置停用会阻止新上传，已发布下载仍可通过保留的配置读取。

## 准备与发布

1. 创建 SemVer 版本，选择 `latest` 正式通道或 `nightly` 预览通道。正式通道不接受预发布版本。填写实际系统要求与更新说明。
2. 每个目标添加完整文件：Windows x64 / ARM64 均为 EXE 与 EXE.blockmap；Mac ARM64 / x64 为 DMG、ZIP 与 ZIP.blockmap。后台批量选择文件后自动按扩展名识别用途，默认存储自动分配 `前缀/clients/版本/目标/唯一文件路径`，无需输入下载地址或校验值。高级 API 保留旧外链与转存兼容能力。带临时查询凭据的地址只能用于转存，服务端加密保存来源地址。
3. 服务端持久化处理任务，流式计算 SHA-512、SHA-256 和大小，检查 blockmap 格式、对应包大小和更新包 Range 响应。重启后过期任务租约可被接管，失败任务需明确重新校验。大文件转存使用临时磁盘，需预留空间；单文件上限 20 GB，单个任务最多运行 2 小时。
4. 选择目标并“检查发布条件”，取得 15 分钟有效的发布计划。确认发布时再次检查版本修订、文件与通道修订，在同一个数据库事务中切换全部所选通道。CLI 重复提交同一计划只回查结果。通道只向更高 SemVer 版本推进。

首次发布后版本资料和文件冻结；应先准备这个版本需要的所有目标，再发布。可以分批把已经准备好的其他目标加入通道。新增文件或修改说明请创建新版本。正式通道会同步设置对应下载页推荐项；预览通道发布也会出现在公开下载目录。

引用外部地址时，文件提供方必须保证地址长期有效且内容不可覆盖；平台登记冻结不能阻止外部服务修改文件。需要由本平台控制保留期限时，请选择上传或转存。

“下架”移除公开目录入口，清空仍指向此版本的更新通道，并保留通道修订号。它不会自动降级、撤回已下载文件或切回上个版本。历史二进制和 blockmap 的固定地址继续可读，供后续版本差分更新使用。重新恢复推送请发布更高版本的修复包。

## CLI

组织登录与平台登录使用独立的系统凭据库条目。由本人在浏览器选择 `releases.write`（维护文件）、`releases.publish`（发布/下架）与 `storage.manage`（配置存储）；只读查询不需要这三个写权限。每次调用重新检查平台运营身份。

```sh
actvero auth login --target platform --server https://platform.example.com
actvero auth status --target platform --server https://platform.example.com
actvero storage list --server https://platform.example.com
actvero storage save <storage-uuid> --file storage.json --server https://platform.example.com
actvero storage test <storage-uuid> --server https://platform.example.com
actvero releases import --file client-release.json --storage <storage-uuid> --server https://platform.example.com
actvero releases show <release-uuid> --server https://platform.example.com
actvero releases jobs --artifact <artifact-uuid> --server https://platform.example.com
actvero releases plan <release-uuid> --revision <revision> --targets win-x64,mac-arm64 --server https://platform.example.com
actvero releases publish <release-uuid> --plan <plan-uuid> --server https://platform.example.com
```

`import` 检查文件摘要和清单中的 `feed_roots` 与目标平台一致，按平台与版本生成稳定版本编号，按目标、用途与摘要生成稳定文件编号。同一份清单可以恢复分片；服务端合并响应丢失时先回查对象，不重新生成一个发布版本。多架构清单可分别导入同一个未发布草稿。导入只进入校验，不自动发布。

`releases artifact-add` 接受外链或转存 JSON，`verify` 重试处理任务，`upload-status` 查看上传，`upload-abort` 取消未完成上传。`artifact-remove --revision` 移除草稿文件的登记；已写入的对象不会立即删除。`heads` 查询当前通道，`withdraw --revision` 下架。`storage save` 和 `releases save` 使用完整请求与 `expected_revision`；冲突先读取现有记录。离线说明见 `actvero guide show distribution`，字段见 `actvero schema show StorageSave`、`DistributionSave`、`ArtifactCreate`。

## 桌面构建与差分下载

DSH 构建时把 `DSH_DESKTOP_UPDATE_BASE_URL` 设置为 `https://platform.example.com/api/v1/client-updates/actvero`，并选择 `DSH_DESKTOP_UPDATE_CHANNEL=latest` 或 `nightly`。配置必须来自桌面构建配置文件，已安装的客户端不会因中台配置改变而自动改用新更新源。首次迁移需要安装一个使用该更新源构建的版本。

桌面构建目录完成签名与打包后，使用桌面仓库的 `export:client-release` 导出 `client-release.json`。发布清单只引用同目录或子目录文件，不读取相邻个人仓库；CLI 安装包包含自己的接口契约和手册。

更新接口为 `/api/v1/client-updates/actvero/{target}/latest.yml`，Mac 使用 `latest-mac.yml`，预览通道替换为 `nightly` / `nightly-mac.yml`。清单由平台生成，引用包含版本号的固定文件入口；对象可使用独立随机存储路径。旧版 blockmap 使用同一文件命名规则，兼容 electron-updater 的旧版本地址推导。

差分下载由 electron-updater 执行：读取新旧 blockmap，复用本地已有数据，使用单段 Range 获取变化部分，校验完整新文件。它并非任意安装包都能生成的补丁，也不保证每次都能减少下载量。Mac 首次更新或缺少旧 ZIP 缓存时通常回退全量；Windows 需要启用 differentialPackage 的 NSIS 包。签名、公证、应用标识、发布者身份和系统支持仍由桌面构建流程负责。

客户端可在管理更新源构建中显式设置 `DSH_DESKTOP_MANDATORY_UPDATE_DISABLED=1`，不嵌入上游强制更新策略；普通构建的策略校验保持原行为。平台当前不提供强制更新策略服务、灰度比例或自动回滚。文件摘要和 blockmap 校验不能代替真实签名验证、CDN 资格测试与旧版本到新版本的安装升级测试。

## 服务端接口与运行

Web 管理前缀为 `/api/v1/platform/client-distribution`，使用登录 Cookie、Origin 与 CSRF；CLI 前缀为 `/api/v1/management/platform/client-distribution`，只接受独立 CLI 平台 Bearer，拒绝 Web Cookie/Origin 和组织凭据。二者共享领域服务。公开 feed 和固定文件入口不需要用户登录。

启用 `ACTVERO_CLIENT_DISTRIBUTION_WORKER_ENABLED`（默认 true）运行持久化处理任务。`ACTVERO_CLIENT_DISTRIBUTION_ALLOWED_PRIVATE_ORIGINS` 默认为空；确需内网 HTTPS 下载时，由部署人员按完整来源显式放行。外链与每次重定向都经 DNS 地址校验并固定连接目标；来源 URL 不出现在任务错误或日志中。

必须先应用数据库迁移，再启动新服务。部署后台服务无需构建或访问桌面仓库。API 细节以 [OpenAPI](api/openapi.json) 为准。

## 原生构建与 CLI 上传

在桌面源码仓库中构建，平台仓库不会读取相邻项目。Windows x64 / ARM64 分别在对应架构的 Windows 构建机生成，Mac 构建机生成 Mac ARM64 / x64。Windows ARM64 使用原生 ARM64 Node、Python 和 Python 扩展；构建机也须运行 ARM64 Node，签名与安装验收在 Windows ARM64 环境完成。

先在桌面打包配置（`.env.windows` / `.env.macos`，或既有机器 preset）固定更新源和通道：

```dotenv
DSH_DESKTOP_UPDATE_BASE_URL=https://platform.example.com/api/v1/client-updates/actvero
DSH_DESKTOP_UPDATE_CHANNEL=latest
DSH_DESKTOP_MANDATORY_UPDATE_DISABLED=1
```

最后一项仅适用于采用平台更新源且明确不用上游强制更新策略的构建。业务登录默认地址与此更新地址分别配置，改变后台存储不会改变客户端内置更新源。迁移旧客户端必须先安装内置本平台更新源的版本。两个构建机使用同一干净源码提交和已确定版本，沿用桌面项目的版本、签名与公证配置。

```sh
# 在各自系统的桌面仓库运行一个对应目标
pnpm client:build win-x64
pnpm client:build win-arm64
pnpm client:build mac-arm64
pnpm client:build mac-x64
```

快捷命令调用原生签名打包，成功后在 `apps/desktop/.desktop-build/targets/<目标>/artifacts/client-release.json` 写出清单。Mac x64 在 Apple 芯片上仍需满足桌面项目的 Rosetta 要求。已有合格产物也可单独运行 `pnpm client:export <产物目录> <目标> --minimum-os <系统要求>`；不覆盖已有导出，过期清单需要先明确移除。

```sh
actvero auth login --target platform --server https://platform.example.com
actvero releases import --dir ./apps/desktop/.desktop-build/targets/mac-arm64/artifacts --server https://platform.example.com
```

CLI 默认使用平台默认存储，支持 `--storage <UUID>` 显式覆盖。清单包含 schema_version=1、version、channel、source_commit、minimum_os、feed_roots 和精确文件列表。CLI 先核对所有文件摘要与包内更新源，按版本查找并合并草稿；源码提交或已有资料冲突会停止。每个构建机保留自己上传任务的用户身份；不共享令牌或对象存储密钥。

导入默认等待本次目标的校验，`--no-wait` 只上传，`--timeout <秒>` 调整等待时间。`releases wait <UUID>` 继续等待，`releases retry <UUID>` 重试失败文件的校验，`releases jobs --artifact <UUID>` 查看错误。所有目标就绪后再 plan / publish；首次发布冻结文件，后续补目标文件需新版本。重复导入使用稳定编号及原文件续传，不会自动发布。

## 下载访问与维护

更新清单和网站安装下载都引用平台的固定版本化 URL。私有桶模式每次请求生成一小时 GET 签名并 307 跳转，文件字节由对象存储传输；跳转支持客户端重新携带 Range。签名 URL 不持久化到版本、通道或审计。公开 CDN 模式兼容既有地址。安装包属于公开发布内容，公开版本入口无需用户登录；知识库等私有资源必须由各自业务权限决定是否签发下载凭据。

保存所有已发布安装包、ZIP 与 blockmap，禁止覆盖相同版本的对象。只清理未完成 multipart 和确认未被引用的草稿对象；平台没有自动删除历史对象的任务。临时链接失效后重新请求平台固定入口，不保存临时链接。存储凭据轮换可编辑原配置，迁移桶需新增配置并设计历史对象迁移，不能直接覆盖已使用配置的定位字段。

服务升级应先运行数据库迁移 `118m_release_provenance`，部署 API 与后台，再使用新版 CLI（`client_distribution_contract_version=2`）。旧存储接口路径继续兼容，新共享接口为 `/platform/object-storage` 及对应 management 路径。真实供应商/CDN 的 Range、Win/Mac 签名和旧版升新版测试需在实际发布环境完成。


Windows ARM64 的更新目标为 `win-arm64`，安装包和 EXE.blockmap、最低系统要求、网站推荐与更新通道均与 `win-x64` 分开。默认系统标签为 Windows 11 ARM64。旧 x64 客户端保留自己的更新源，不会通过升级跨架构替换。可用 `client_distribution.win_arm64` 检查服务器兼容性。Windows 的 NSIS 安装器辅助界面仍使用 x86 插件，应用及内置解释器使用所选架构；需要在实际 Windows ARM64 系统验证安装、启动、卸载和旧版升级。
