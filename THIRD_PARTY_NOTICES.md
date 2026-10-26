# Third-party notices

Actvero's project code is licensed under MIT. Third-party code, dependencies and artwork remain subject to their own licenses. Package versions are recorded in the relevant lockfiles; imported source and asset provenance is recorded in `docs/upstream.lock.json`.

| Included source or artwork | Location | License record |
| --- | --- | --- |
| Shadcn Admin | `frontend/` | `frontend/LICENSE` — MIT, Sat Naing |
| Lobe Icons provider avatars | `frontend/src/assets/provider-avatars/` | Included `LICENSE` and asset `README.md` — MIT, LobeHub |
| Magic UI Magic Card adaptation | `frontend/src/features/portal/effects.tsx` | `frontend/public/notices/magic-ui.txt` — MIT |
| Lucide / Feather-derived icon assets | Frontend icon usage and `backend/app/modules/skills/assets/icons.json` | `frontend/public/notices/lucide.txt` — full notice from the locked dependency, including applicable Feather attribution |

Names and marks used to identify third-party providers belong to their respective owners. Their presence does not imply endorsement or support for every provider capability.

License notices must be retained when redistributing the relevant code or assets, including in container builds. This index complements the included license texts; it does not replace them.

## S3 SDK

客户端对象存储使用 Boto3 / Botocore（Amazon Web Services，Apache-2.0）处理签名和 multipart 协议。直接依赖固定为现有锁定环境中的 Boto3 版本；保留依赖包内的许可证和版权信息。
