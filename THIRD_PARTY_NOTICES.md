# Third-party notices

Actvero's project code is licensed under MIT. Third-party code, dependencies and artwork remain subject to their own licenses. Package versions are recorded in the relevant lockfiles; imported source and asset provenance is recorded in `docs/upstream.lock.json`.

| Included source or artwork | Location | License record |
| --- | --- | --- |
| Shadcn Admin | `frontend/` | `frontend/LICENSE` — MIT, Sat Naing |
| Lobe Icons provider avatars | `frontend/src/assets/provider-avatars/` | Included `LICENSE` and asset `README.md` — MIT, LobeHub |
| Magic UI Magic Card adaptation | `frontend/src/features/portal/effects.tsx` | `frontend/public/notices/magic-ui.txt` — MIT |
| Lucide / Feather-derived icon assets | Frontend icon usage and `backend/app/modules/skills/assets/icons.json` | `frontend/public/notices/lucide.txt` — full notice from the locked dependency, including applicable Feather attribution |
| Tabler Apple and Windows icons, v3.35.0 | `frontend/src/assets/platforms/` | `frontend/public/notices/tabler-icons.txt` — MIT, Paweł Kuna; unmodified SVGs from the pinned [Tabler Icons release](https://github.com/tabler/tabler-icons/tree/v3.35.0/icons/filled) |

Names and marks used to identify third-party providers belong to their respective owners. Their presence does not imply endorsement or support for every provider capability.

License notices must be retained when redistributing the relevant code or assets, including in container builds. This index complements the included license texts; it does not replace them.

## S3 SDK

客户端对象存储使用 Boto3 / Botocore（Amazon Web Services，Apache-2.0）处理签名和 multipart 协议。直接依赖固定为现有锁定环境中的 Boto3 版本；保留依赖包内的许可证和版权信息。

## New API gateway interface

The channel and model management UI includes adapted source from [QuantumNous/new-api v1.0.0-rc.47](https://github.com/QuantumNous/new-api/tree/v1.0.0-rc.47/web/src), copyright QuantumNous and contributors. It is governed by AGPL-3.0-or-later and the upstream additional attribution terms, separately from Actvero’s MIT license. See the bundled [LICENSE](frontend/src/vendor/newapi/LICENSE), [NOTICE](frontend/src/vendor/newapi/NOTICE), and [integration notes](frontend/src/vendor/newapi/README.md).

## Model capability references

The generated model capability snapshot uses [earendil-works/pi](https://github.com/earendil-works/pi), pi-ai 1.1.0, copyright Mario Zechner, and native DeepSeek capability definitions from [deepseek-ai/deepseek-harness dsh-v0.2.1-rc.2](https://github.com/deepseek-ai/deepseek-harness/tree/dsh-v0.2.1-rc.2), copyright DeepSeek. Both are MIT-licensed; full notices accompany the generated data in `backend/app/modules/model_gateway/data/`. These capability references do not supply Actvero prices or upstream inventory.

The native New API organization bridge and billing preflight overlay and reproducible gateway build are in `integrations/newapi/`; redistribution of the combined gateway retains upstream AGPL and attribution requirements.
