# 管理命令

```sh
actvero auth login --server https://actvero.example.com
actvero auth status --json
actvero org list --page 1 --json
actvero org show --org <组织 UUID> --json
actvero org permissions --org <组织 UUID> --json
actvero channels list --org <组织 UUID> --page 1 --state current --json
actvero channels list --org <组织 UUID> --q DeepSeek --json
actvero channels show --org <组织 UUID> --id <渠道 UUID> --json
actvero auth logout
```

每条命令都可通过 `--server` 显式指定平台；缺省只使用上次成功登录的平台地址。登录没有默认组织，读命令没有隐含写入、测试或自动发布。更换账号先退出原 CLI 登录，再用 `auth login --reauthenticate`。

退出码：0 成功；1 业务、网络或凭据保存失败；2 参数错误；130 用户中断。JSON 成功输出到 stdout，平台错误对象输出到 stderr。参数解析错误仍采用 argparse 的终端格式。

当前未提供模型、MCP、Skills、专家管理以及渠道编辑、启停、删除、模型测试。安装版本的 `--help` 是命令是否可执行的依据，开发计划不是可用能力。
