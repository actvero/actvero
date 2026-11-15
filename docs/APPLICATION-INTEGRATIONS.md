# 应用集成

本文供组织管理员和接入开发者使用。完成配置后，Odoo、机器人等外部服务可用一个应用 Key 同步模型、MCP、Skills、专家，管理应用自身的知识库并检索组织共享资料。

## 连接与鉴权

1. 在「组织管理 → 应用集成」创建应用。生产和测试环境建议各用一个应用。
2. 在「权限」按需要开启模型、MCP、Skills、专家、知识库。五项独立控制，打开某项后，同范围内新开放的资源自动可用。
3. 在「密钥」生成 Key，把它保存到接入系统的后端。完整 Key 只在生成时展示。换 Key 时先签发新 Key，在调用端切换后撤销旧 Key。
4. 在「接入」复制集成 API 地址，令 `ACTVERO_API` 指向该地址（以 `/api/integrations/v1` 结尾），把 Key 注入 `ACTVERO_KEY`。以下命令在接入服务器执行：

```sh
curl --fail-with-body -H "Authorization: Bearer $ACTVERO_KEY" "$ACTVERO_API/me"
```

响应含 `application_id`、`name`、五个 `*_enabled` 开关、`integration_base_url` 和 `model_base_url`。其他请求使用同一个 `Authorization` 头。接入服务端应使用 HTTPS，应用 Key 不传给浏览器、iframe 或其他上游。后台「API 文档」链接提供 Swagger 界面，[OpenAPI](api/openapi.json) 收录所有请求、响应和字段约束。调试应用 Key 使用时，命令行客户端无需携带后台 Cookie 或浏览器 Origin。

| 能力 | 范围 |
| --- | --- |
| 模型 | 本组织已开放的模型与操作，可发现和调用 |
| MCP | 本组织全员可用且启用的服务，使用组织凭据或免认证连接 |
| Skills | 本组织全员可用且已发布的技能包 |
| 专家 | 本组织全员可用且已发布的专家清单与依赖 |
| 知识库 | 本组织全员可用的库可读取和检索。应用自建库还可更新、上传、重建、删除和归档 |

应用属于一个组织。创建它的管理员离开组织不会使应用失效。管理员可在后台停用应用、关闭能力、撤销密钥。现有逐模型授权升级后需手动打开模型开关。各新增能力默认关闭。后台用户应继续在模型网关、MCP、Skills、专家等业务页面配置和发布资源。管理员也可用 [管理 CLI](CLI.md) 自动化常规资源配置与发布。

除模型与 MCP 协议网关外，以下路径均相对于 `ACTVERO_API`。目录从 `page=1` 开始，每页 20 条，依据 `total` 或 `has_more` 决定是否继续。同步失败时保留上次成功的目录。资源下架、组织状态或应用授权变化后，后续调用以服务端判断为准。

## 模型

将 `ACTVERO_MODEL_URL` 设置为 `me.model_base_url`，路径以 `/api/llm/v1` 结尾。模型目录以 `data`、`page`、`has_more` 分页。每个条目的 `id` 是调用时使用的模型标识，`operations` 含操作类型、参数、模态和限制。按该条目的操作类型选择接口。模型参数由已开放的配置和可用路由决定。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /models` | 可用模型与参数 |
| `POST /chat/completions` | 对话、工具调用、SSE 流式输出 |
| `POST /embeddings` | 向量 |
| `POST /rerank` | 重排序 |
| `POST /images/generations` | 单张图像生成 |
| `POST /audio/speech` | 语音合成 |
| `POST /audio/transcriptions` | 音频转写 |

```sh
curl --fail-with-body -H "Authorization: Bearer $ACTVERO_KEY" \
  "$ACTVERO_MODEL_URL/models?page=1"

curl --fail-with-body -H "Authorization: Bearer $ACTVERO_KEY" \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: order-summary-7' \
  --data '{"model":"your-model-id","messages":[{"role":"user","content":"总结这份订单"}]}' \
  "$ACTVERO_MODEL_URL/chat/completions"
```

调用费用归组织和发起应用。后台可查看结果、结算状态和金额。支持 `Idempotency-Key` 的调用按应用识别已受理请求，换 Key 后仍可查询。同标识再次提交返回 `409` 和原调用标识，不重新发送；用 `GET /calls/{call_id}` 查询本应用的回执。调用结果与结算状态独立，缺失计量不能视为零。各操作的参数见 [模型客户端参数](LLM-CLIENT-PARAMETERS.md) 和 [OpenAPI](api/openapi.json)。

## MCP

`GET /mcp/services?page=1&q=...` 返回服务 ID、名称、简介、配置版本和 Actvero 网关 `endpoint`。对每个 `endpoint` 使用相同应用 Bearer Key，通过无状态 MCP Streamable HTTP 同步和调用。只使用目录返回的网关地址。组织凭据由 Actvero 管理，个人凭据与个人 OAuth 服务不进入应用目录。若 `configured=false`，由组织管理员配置连接。

在 `POST` 请求中同时提供 `Accept: application/json, text/event-stream` 和 `Content-Type: application/json`。先发 `initialize`，按协商版本发送 `MCP-Protocol-Version`。当前支持 `2025-11-25`、`2025-06-18`、`2025-03-26`。网关不分配会话 ID。

```sh
curl --fail-with-body -H "Authorization: Bearer $ACTVERO_KEY" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"example-client","version":"1.0.0"}}}' \
  "$MCP_ENDPOINT"
```

| JSON-RPC 方法 | 参数与用途 |
| --- | --- |
| `tools/list` | 工具定义与 `inputSchema` |
| `tools/call` | `name`、`arguments`，按定义执行工具 |
| `prompts/list`、`prompts/get` | 获取提示词目录，按 `name` 和文本 `arguments` 读取 |
| `resources/list`、`resources/templates/list` | 获取资源和模板目录 |
| `resources/read` | 以 `uri` 读取已开放资源或模板匹配的资源 |
| `ping` | 连接探测 |

例如工具调用正文为 `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"lookup","arguments":{"id":"A123"}}}`，其中工具名和参数来自实时目录。JSON-RPC `error` 可能由 HTTP 200 返回，应同时检查 `error` 和工具结果中的 `isError`。有副作用的工具超时后先核对上游状态，网关不会自动重发。管理员停用工具或工具定义发生未确认变化后，该工具不再可调用。

## Skills

| 方法与路径 | 输入与返回 |
| --- | --- |
| `GET /skills?page=1&q=...` | 当前发布，包含 Skill ID、`revision`、版本与摘要 |
| `GET /skills/{skill_id}` | `skill_md`、`entrypoint`、文件清单和当前版本 |
| `GET /skills/{skill_id}/file?version_id=...&path=...` | 读取当前版指定文本文件。路径来自详情 |
| `POST /skills/{skill_id}/download` | JSON 传入 `version_id`、`sha256`，下载 ZIP |

在本地校验 ZIP 的 SHA-256，与 `X-Content-SHA256` 和目录摘要一致后再安装。版本变化会返回 `409`，应刷新目录并重新确认。为专家准备固定依赖时，下载请求另带 `expert_id`、`expert_release_id`，并使用发布清单绑定的技能版本和摘要。撤回技能当前发布或缩小其使用范围后，固定依赖也不能继续下载。

## 专家

| 方法与路径 | 输入与返回 |
| --- | --- |
| `GET /experts?page=1&q=...` | 专家目录和生效发布 ID、版本、SHA-256 |
| `GET /experts/{expert_id}` | `manifest` 和 `dependency_refs`。可传当前 `release_id` 避免静默换版 |
| `POST /experts/{expert_id}/resolve` | JSON 传入当前 `release_id`、`sha256`，检查精确依赖 |

先读取专家清单，再调用 `resolve`。仅在 `can_prepare=true` 时准备全部必需依赖。按返回的 `dependencies` 下载固定版本的 Skills、连接返回的 `mcp_endpoint`。Skills 和 MCP 依赖分别要求对应开关；受专家发布约束的 MCP 地址还会校验当前发布、连接器开放状态和工具范围。连接需要配置、上游能力变化或依赖被撤回时，按依赖状态处理。专家的执行环境由接入宿主提供，Actvero 接口提供发布清单、依赖解析、模型与 MCP 能力。

## 知识库

将 `KB` 设置为 `$ACTVERO_API/knowledge/bases`。可先读 `GET /knowledge/bases/defaults`，返回默认检索策略、配置版本及向量和重排模型选项。建库可传 `defaults_version` 固化默认策略，或明确提交 `retrieval`。使用向量或混合检索时提交向量模型 ID。后台索引与检索调用库已配置的模型，可独立于应用的直接模型开关使用。

| 方法与路径（相对 `KB`） | 输入与返回 |
| --- | --- |
| `GET /?page=1&q=...` | 库列表与状态 |
| `POST /?creation_id=UUID` | 创建知识库，返回库 ID 与初始配置 |
| `GET /{base_id}` | 当前设置、`version` 和 `can_manage` |
| `PUT /{base_id}` | 带当前 `version` 更新应用自建库 |
| `DELETE /{base_id}` | 归档应用自建库，停止检索和原文访问 |
| `GET /{base_id}/documents` | 文档列表与各文档的处理状态 |
| `POST /{base_id}/documents?filename=...&upload_id=UUID` | 以二进制上传原件，返回文档和处理版本 |
| `GET /{base_id}/documents/{document_id}` | 处理状态、切片和原文位置，支持 `generation_id`、`page`、`q` |
| `POST /{base_id}/documents/{document_id}/chunk-preview` | 试算切片与原文定位，取得可用于重建的 `preview_token` |
| `POST /{base_id}/documents/{document_id}/rebuild` | 带当前 `generation_id` 重建，支持指定切片参数 |
| `DELETE /{base_id}/documents/{document_id}` | 删除文档并撤销引用 |
| `GET /{base_id}/documents/{document_id}/source` | 获取原件 |
| `POST /{base_id}/search` | `query`、`limit`、可选 `rerank`，返回引用与命中 |
| `GET /{base_id}/citations/{chunk_id}` | 读取引用与原文位置 |
| `POST /{base_id}/citations/{chunk_id}/reader-session` | 以 `parent_origin` 签发短期原文阅读凭证 |

```sh
curl --fail-with-body -H "Authorization: Bearer $ACTVERO_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"name":"采购手册","retrieval":{"mode":"keyword"}}' \
  "$KB?creation_id=$CREATION_UUID"

curl --fail-with-body -H "Authorization: Bearer $ACTVERO_KEY" \
  -H 'Content-Type: application/octet-stream' --data-binary @guide.txt \
  "$KB/$BASE_ID/documents?filename=guide.txt&upload_id=$UPLOAD_UUID"

curl --fail-with-body -H "Authorization: Bearer $ACTVERO_KEY" \
  -H 'Content-Type: application/json' --data '{"query":"采购审批","limit":5}' \
  "$KB/$BASE_ID/search"
```

示例 UUID 由调用端生成并按业务操作保存。建库在同一应用下用相同 `creation_id` 和配置重试会返回原库。上传在同一库内使用相同 `upload_id`、文件名和原件重试会返回原文档。更改正文后应使用新标识。单文件最多 20 MiB，每库最多 100 份文档。对文件名等查询参数做 URL 编码。

上传成功不等于可检索。轮询文档状态，在 `ready` 后开始检索。失败时读取 `error`，纠正配置后重建。换 Key 不影响已受理任务。关闭知识库权限或停用应用会停止后续阶段。重建保留旧的可用索引，直至新处理版本生效。

引用的 `source_url` 是受保护的原件地址。宿主可用引用内容自行绘制角标和悬浮卡片。点开时，宿主后端先检查自己用户的访问资格，再申请短期阅读凭证。前端只接收 `viewer_url`、`token`、`parent_origin` 和有效期，通过 [阅读器消息协议](KNOWLEDGE.md#宿主集成与嵌入阅读器) 进行嵌入。停用应用、关闭能力、撤销签发 Key 或删除原件会影响后续访问。

## 错误与同步

| 结果 | 接入方处理 |
| --- | --- |
| `401` | 检查 Key 是否到期或撤销，更新接入配置 |
| `403` | 检查应用状态、能力开关和操作权限 |
| `404` | 刷新目录。资源可能不属于当前组织、不可见或已下架 |
| `409` | 检查错误码、版本、摘要或重复请求信息，再决定刷新与重试 |
| `413/415/422` | 检查文件大小、媒体类型或字段约束 |
| `429/503` | 按 `Retry-After` 或退避策略恢复读取，保留已成功同步的数据 |
| `502/504` | 核对上游状态。已发出的调用可能产生费用或有业务结果 |

接口错误体含 `error.code`、`error.message`，需要排查时保存请求标识。同步时使用资源 ID、版本或摘要识别变更。身份、权限、密钥生成及撤销等后台操作走组织管理员会话，详见 OpenAPI 的 `application-integrations` 标签。
