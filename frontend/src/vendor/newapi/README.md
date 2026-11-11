# New API gateway UI

This directory contains the shared channel creation/editing form, channel card, table primitives, model-testing UI, model and vendor management, metadata sync and pricing UI and their local dependencies from [QuantumNous/new-api v1.0.0-rc.47](https://github.com/QuantumNous/new-api/tree/v1.0.0-rc.47/web/src). The upstream source is licensed under AGPL-3.0-or-later with the additional attribution terms in [NOTICE](NOTICE). Actvero's MIT license does not replace these terms.

Upstream copyright headers, [LICENSE](LICENSE), and NOTICE are preserved. Distributed changes must comply with the upstream license, including corresponding-source and visible attribution requirements.

Actvero modifications:

- Internal imports use the `@newapi` namespace so upstream UI primitives can coexist with Actvero components.
- `lib/api.ts` delegates allowed native operations to the Actvero organization-authorized backend. Native administrator tokens stay on the server. New API login, token generation, and key disclosure are not exposed through this adapter.
- `channels-provider.tsx` supplies the host's close callback and current channel ID for creation and editing.
- `lobe-icon.tsx` uses Vite's explicit lazy module inventory instead of Rspack's dynamic import context.
- Both create and edit use the same full-screen `ChannelMutateDrawer`. The host passes only an existing channel ID; native detail loading supplies provider-specific settings, and an `If-Match` snapshot protects edits from stale configuration. Stored channel keys are omitted from details and blank key input preserves the credential. Key disclosure controls are not enabled.
- The request-policy link is connected through the host integration.
- Actvero supplies its theme variables, session, and a query cache scoped to the current organization.
- The account menu exposes Open-source notices, which retains the upstream frontend attribution and original-project link without occupying page actions or the pagination footer.
- Native synchronization dialogs retain their upstream sizing, nested source selection and scrolling. The shared stylesheet includes upstream's dynamic viewport and safe-area variables so dialog height constraints remain effective on short and mobile screens.
- Channel cards and model tests accept Actvero's safe channel view. Cards currently receive ordinary rows; native tag aggregation is separate. Host-owned action and formatting state is supplied through context so card and table controls stay mounted during background refresh.
- Native test GET calls become CSRF-protected Actvero POST operations. Model-list replacement uses a current revision and rejects a changed model snapshot. Native administrator tokens and channel keys remain on the server.
- The data-table barrel retains the upstream exports used by channels and model management. Field schedulers support cancellation when the host editor unmounts; blur and Enter still commit edits.
- Native model/vendor tables use the Actvero models route and its native search schema. Cloud GPU deployments are not included. An optional organization-access action opens the Actvero policy editor.
- Model metadata updates use the detail snapshot captured when the native form loads; native source/record, vendor and price versions remain intact. Each organization has a separate query client.
- Price-edit capability follows the Actvero organization-admin presentation grants; the server and configured native token recheck every operation. Combobox trigger buttons explicitly retain native button semantics.
- The provider picker adds an Ark Agent Plan preset backed by native Advanced Custom routes. It fills connection paths without supplying a model inventory, recognizes the preset again when editing, and reports the result of server-side ordinary Ark list-price initialization.

The upstream form schema, provider selection, conditional fields, model mapping, validation, and create/update payload transformations remain the source of behavior. Changes to these files should be compared against the pinned upstream version rather than independently redesigning the flow.

## 模型资料与原生统计适配

模型窗口保留原生资料、定价和渠道关联组件，Actvero 将能力与限制加入资料保存，并提供独立的使用设置。管理员测试保留原生请求适配，展示诊断用途、未计价状态和已返回用量。

数据看板的模型调用分析、分流与用户统计组件同样取自上述固定版本。路由、登录身份及查询缓存由 Actvero 提供，主题读取宿主主题；图表使用原生 VChart 依赖。前端不提供跨组织用户名筛选，后端桥接始终限定当前组织的调用身份与分组。源码及相关许可证保留于本目录。
