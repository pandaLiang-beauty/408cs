# 图床

点击页面左上角标题旁的「图床」，即可在当前页面打开快捷浮层，不会跳转或中断批注编辑。
旧地址 `/images` 会转到首页并打开同一个浮层。

1. 点击「选择图片」，拖入图片，或按 Ctrl+V / ⌘V 粘贴截图；也可使用「粘贴图片」按钮。
2. 上传完成后，点击图片卡片中的「复制 Markdown」。
3. 关闭浮层或点击浮层外，继续在原来的批注里粘贴链接并保存。

「复制直链」只复制图片地址。最新上传的图片和复制按钮直接显示，点击「历史图片」可展开旧图片。
点击缩略图可放大预览。粘贴截图只在浮层内生效，关闭后不影响批注的正常粘贴。
上传期间可以收起浮层，上传继续进行，再次打开即可获取链接。
支持 PNG、JPEG、WebP 和 GIF，每张最多 8 MB，可批量上传；某张失败不会影响其他图片。

图片独立保存，不依附任何笔记或批注；关闭页面、重新登录或删除批注不会使图片链接失效。
上传和列表需要登录，图片直链无需登录，持有链接即可查看原图。
公开地址沿用 `.env.local` 的 `STUDY_PUBLIC_BASE`；未配置时复制当前浏览器站点的完整地址。

## 存储与备份

文件保存在 `backend/data/image_host/`，元数据保存在 `study.db` 的 `hosted_images` 表。
备份与迁移时同时保留数据库和图片目录；构建前端、重启服务不会清理这些文件。
公网域名需要保持稳定，域名变更后此前复制的绝对链接需要更新或保留旧域名转发。

接口：登录后 `POST /api/image-host` 上传、`GET /api/image-host` 分页读取；
`GET /api/image-host/files/{随机文件名}` 返回图片原始内容。文件名使用随机值，上传时按实际图片头识别格式。

## 验证

后端测试依赖见 `backend/requirements-dev.txt`。在 `backend/` 运行
`.venv/bin/python -m unittest test_image_host test_note_images test_annotations`；
在 `frontend/` 运行 `npm test` 和 `npm run build -- --emptyOutDir false`。
