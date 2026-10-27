# 客户端发布：存储、上传与通道

此入口使用独立平台授权，不需要 `--org`。先检查 `platform info` 中的 `client_distribution.read/write`、`client_distribution.import_manifest` 和 `object_storage.read/write`，再运行 `auth status --target platform`；需要时用 `auth login --target platform` 在浏览器授权维护文件、发布版本和管理存储。组织会话不能代替平台会话。

## 操作顺序

1. `storage list` 读取已有配置。新增或修改用 `storage save <UUID> --file <JSON>`，字段见 `schema show StorageSave`；包含 expected_revision，已有密钥留空保留。保存后用 `storage test <UUID>` 检查。
2. 从桌面构建输出取得 `client-release.json`，运行 `releases import --dir <产物目录>`，也可用 `--file <JSON>`。结构可用 `example show client-release` 查询，实际清单由构建导出而不是手写摘要。清单含 schema_version=1、version、channel、source_commit、minimum_os、feed_roots 与 artifacts；每个文件提供 target、role、相对 file、size_bytes 和 base64 SHA-512。CLI 在写入前检查摘要和更新源。清单必须包含完整 source_commit，旧清单用新版桌面导出命令重新生成；已有文件却没有源码提交记录的旧草稿使用新版本继续。默认使用平台设置中的默认存储；`--storage <UUID>` 仅用于明确覆盖。不同架构按版本号合并到同一草稿，源码提交和通道必须一致；其他目标已有的系统要求会保留。
3. 导入默认等待本次目标的校验完成，`--timeout <秒>` 调整上限，`--no-wait` 上传后返回。使用 `releases show <UUID>`、`releases jobs --artifact <UUID>` 回查；`releases wait <版本UUID>` 继续等待全部文件；失败后可 `releases retry <版本UUID>` 重试失败校验，或 `releases verify <artifact UUID>` 重试单个文件。
4. 所需文件均已校验后，读取当前 revision，运行 `releases plan <UUID> --revision <n> --targets win-x64,win-arm64,mac-arm64,mac-x64`，只列出本次实际发布的目标。核对计划后，用 `releases publish <UUID> --plan <plan UUID>` 发布。
5. `releases heads` 与 `releases show` 回查结果。下架使用 `releases withdraw <UUID> --revision <n>`，不自动降级或切回旧版本。

每条联网命令均显式带 `--server <URL>`。导入和校验不会自动发布；发布属于用户任务授权范围时可继续执行，无需按本手册另加确认。

## 上传与恢复

清单导入使用稳定版本和文件编号。传输中断后使用原清单、原文件与同一平台重试；有声明摘要的文件可跳过已确认分片。合并响应不明时先回查远端对象，不重新创建一个版本。`releases upload-status <artifact UUID>` 查看任务，`releases upload <artifact UUID> <file>` 恢复本地文件传输。没有声明 SHA-512 的上传恢复会重传分片，避免混合不同文件。

已有地址用 `releases artifact-add <release UUID> <artifact UUID> --file <JSON>`，字段见 `schema show ArtifactCreate`。长期引用不能带查询参数；临时 URL 使用 mirror=true 和 storage_id 转存。不要在聊天、日志或提交文件中放入存储密钥、临时 URL 凭据或签名上传地址。

未完成的任务可用 `releases upload-abort <artifact UUID>` 取消，再用 `releases artifact-remove <artifact UUID> --revision <n>` 移除草稿登记。文件记录移除不直接删除桶内对象。过期任务需要取消并重新登记。

发布计划有效期 15 分钟；409 先读取版本和通道状态，再生成新计划。同一发布计划可以重复提交回查，不能换一个计划去猜测上次是否成功。这组接口使用资源编号、expected_revision 和 plan_id 恢复，不使用组织资源的 `commands show` 回执。

## 文件与更新边界

Windows x64 / ARM64 提供各自 EXE 和 EXE.blockmap；Mac 每个架构提供 DMG、ZIP、ZIP.blockmap。版本采用 SemVer，latest 不接受预发布号。首次发布冻结整个版本的文件与资料，请先准备全部目标。已准备的目标可分批发布；补新文件使用新版本。

安装包必须用目标平台 feed 构建并完成签名；旧客户端不会自动改用新的更新地址。差分由 electron-updater 和配套 blockmap 执行，不保证每次都能增量下载。Mac 缺少旧 ZIP 缓存时可能全量下载。平台文件校验不是签名验证或真实安装升级验收。

## 构建机与维护规则

Windows 和 Mac 由各自构建机完成。桌面源码提供 `pnpm client:build win-x64`、`pnpm client:build win-arm64`、`pnpm client:build mac-arm64`、`pnpm client:build mac-x64`，保留原生签名、公证与依赖检查，成功后生成清单；无需在构建机安装对象存储 SDK 或配置桶密钥。目标平台与更新源必须在构建配置中选择，不能上传后更改安装包内置的地址。具体配置见平台文档的客户端更新发布指南和桌面打包说明。

两个构建机应使用同一干净源码提交、相同版本号与更新通道；分别上传各自产物目录，不复制另一台机器的上传会话。所有目标准备完毕再首次发布。Windows ARM64 使用运行 ARM64 Node 的原生 Windows ARM64 构建机，安装、启动和升级须在该架构验收。`win-x64` 和 `win-arm64` 的产物、更新源和通道必须分别维护，不能把 x64 文件改名或改 target 作为 ARM64 发布；服务器须提供 `client_distribution.win_arm64`。

存储默认放在平台“设置 → 对象存储”。桶可保持私有：未填写公共根地址时，平台用版本化下载入口生成一小时有效的 GET 签名，密钥与临时下载 URL 不写入版本清单。更新包、blockmap 和安装包必须保留原始字节并支持单段 Range；已发布文件不覆盖、不按年龄清理。下架只停止通道推送与推荐，不删除历史对象，也不自动降级。知识库等模块使用自己的权限控制，不能复用客户端公开下载入口。

上传出错先读取 `show`、`jobs` 和 `upload-status`。修复网络后用同一清单重跑导入；校验失败先排查实际错误再 retry，不循环尝试发布。409 只有记录修订竞争可做有界重读重试，源码或同类文件冲突须停止核对。CLI 标准输出为 JSON，进度走标准错误；不要解析进度文案判定发布结果。


构建提速依赖构建机缓存：桌面脚本把未签名基础输入和运行时 pnpm store 保存在项目内被 Git 忽略的 `apps/desktop/.desktop-build/cache/`，按架构与输入身份复用，无需额外配置。Agent 正常构建不要主动清缓存，也不要用 `git clean -fdx` 处理构建慢。源码目录中的安装包、导出清单、构建日志和临时文件位于被忽略的 `apps/desktop/.desktop-build/`，机器密钥与本地配置不提交；源码、依赖锁和规则说明正常提交。缓存损坏先停止构建，再按错误指出的条目清理；不得跳过签名、摘要和冒烟检查来获取缓存命中。具体首轮与复用轮耗时读取构建记录，不能承诺未经实测的提速比例。
