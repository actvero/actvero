# 错误恢复与停止条件

先记录退出码、error.code/message/status 和已有 request_id，去除秘密后用于交付。平台某些业务错误统一为 request_failed，须结合 status/message；不依赖翻译后的文字做自动重试判断。

## 定位表

| 现象/错误 | 下一步 |
| --- | --- |
| command not found / 同名旧 CLI | 按 bootstrap 固定版本 npx；核对 --version/--help |
| server_required / invalid_server | 明确正确基础 URL；远端 HTTPS，不附加 console/api 或令牌 |
| platform info 404 / management_unavailable / unsupported_contract / unsupported_capability | 核对 URL；读取能力。需平台管理员完成部署/启用，不自行回退到 Web 私有 API |
| login_required | 运行 auth login，由用户在浏览器确认组织和权限 |
| insufficient_scope / organization_not_granted | 运行 auth login，在浏览器调整组织或管理权限，无需先退出 |
| client_upgrade_required / consent_required | 升级 CLI 后运行 auth login，由用户确认授权 |
| consent_identity_mismatch | 浏览器授权与回环登录的账号不同，重新发起并使用同一账号 |
| secure_store_unavailable | 解锁/启用系统凭据库，Linux 检查 Secret Service；不导出/明文存令牌 |
| browser_unavailable / login_timeout / login_cancelled | 需要同机浏览器完成本地回调；修复环境或重新发起登录，不手工拼接回调 |
| issuer_mismatch / invalid_response | 停止登录/写入，核对平台和 CLI 版本/身份配置，不禁用 issuer 校验 |
| session_busy | 当前平台的另一命令持有锁；等其完成后重试，不手工删除锁来强制并发 |
| logout_pending | 原退出未确认，先重试 auth logout，不能继续写入 |
| 401 / 会话失效 | status 核对；需重新认证时用户登录。若已有写入请求，登录后仍先回查原编号 |
| 403 / 组织不可用 | 重新查询 org permissions；确认账号、组织和角色，不尝试别的 org ID 绕过 |
| 404 资源 | 查当前组织列表及分页、确认 ID；不能据此断言其它组织也没有 |
| 409 修订冲突 | 重读最新详情、比较差异、重新构造文件与新请求；不自动覆盖并发修改 |
| command_conflict | 原编号用于不同请求；先回查其原意/结果，不能改编号掩盖未知状态 |
| command_unconfirmed / pending / unknown | 查询原命令及资源状态，不自动重放；无法判定时报告未确认 |
| command_result_not_retained | 原操作已成功但正文未留存；MCP 查活动/目标状态，OAuth 查原 attempt；不要为取正文重复执行 |
| 422 / invalid_file / invalid_number / invalid_id | 读取对应 schema/help；JSON 对象 ≤5 MB、完整 UUID、正整数修订；修改后只在确定未执行时新提交 |
| output_unavailable | 下载目标已存在或不可写，选择新的受控路径，不删除用户已有文件 |
| checksum_mismatch / invalid_download / download_interrupted | 不使用下载内容；查原回执，核对组织/版本，按原编号恢复或报告完整性问题 |
| network_unavailable / 超时 / 5xx | 读请求可在恢复后有界重试；写请求按下方处理 |

## 写入超时/响应丢失

1. 保留原服务器、组织、请求 UUID、文件、方法和目标。CLI 已在发送前输出并将不含正文的编号存入私有配置目录。不要从响应缺失推断服务端没执行。
2. 使用同账号查询：

   ```sh
   actvero commands show <REQUEST_UUID> --server <SERVER> --org <ORG_UUID> --json
   ```

3. succeeded：读取保存结果并用资源 show/列表核验。无保留结果时仅能确认完成状态；MCP run 的输出丢失不能据活动记录重新构造，向用户说明。
4. pending：短暂等待后有限次回查，仍 pending 就报告未确认。unknown：查资源/活动，停止自动重复。回执不存在或403也不等于“没有执行”，先解决账号/权限/请求编号归属。
5. 仅已确认原成功且需取回同请求结果，或下载按设计恢复时，原样保留输入和原 UUID；不自动重放真实副作用。确认原操作未执行/已经失败且原因已修复后，新操作才使用新 UUID。

GET 在 access_expired 时客户端可续期后重试一次；写操作不会自动发送第二遍。这不保证所有外部供应商副作用都具备端到端幂等。

## 批量与迁移请求

先枚举完整分页，冻结授权目标 ID 清单。不同资源逐项读取最新修订号、写入、核验并记录结果，保留各 request_id。范围错误、权限丢失、身份异常或未知执行出现时停止受影响部分；不要把失败项用另一个平台/组织重试。

跨平台“搬运”需要分别登录、确认两边组织、重新建立 ID 映射。MCP export 不含凭据；Skill 下载/导入会生成新 ID；专家精确引用须重建，不能直接复制旧平台 UUID/摘要组合。仅要求“切换维护平台”不授权批量复制资源。

## 最终说明

明确区分失败、未执行、执行结果未知。报告已确认的资源状态、涉及范围和下一步所需信息；不泄露令牌、私有正文、OAuth URL。修复权限、升级目标平台或获取缺少成员 ID 后可以继续，但不能假称仅凭 CLI 代码/测试已在目标平台上线。
