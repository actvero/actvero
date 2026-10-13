# 项目标识与来源

仓库中的 Actvero 图形由两条实心路径组成，几何定义存于 `frontend/src/assets/brand/geometry.json`。共享 React 组件使用 `currentColor` 适配主题。

## 资源

- `frontend/public/brand/actvero-icon.png`：方形图标。
- `frontend/public/brand/actvero-mark.svg`：网页矢量标识。
- `frontend/public/favicon.ico`：浏览器兼容图标。
- `identity/themes/actvero/login/resources/img/`：身份主题使用的同步副本。

`build-identity-theme.py` 从同一几何及构建产物同步身份资源。构建不读取其他仓库。上游素材出处保留在 [来源记录](upstream.lock.json)，用户自定义品牌见 [统一品牌](UNIFIED-BRANDING.md)。

## 参考

[文档导航](README.md) · [API 契约](api/openapi.json)
