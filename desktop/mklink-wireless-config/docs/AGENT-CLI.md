# Agent 操作 Mklink Remote

Mklink Remote 提供工作台、同进程本机服务和 `mklink-remote.exe`。CLI 通过仅绑定回环地址的认证入口访问同一服务，不另开蓝牙或串口。原有 MKLink 技能与远程 MCP 保持原版；无线与服务端适配由 Remote 自己打包和维护。

## 启动与发现

Windows 下在安装目录用 `.\mklink-remote.exe` 执行以下命令，或传入该程序的完整路径。打开工作台即可使用 CLI。无界面环境先运行 `mklink-remote serve`，随后打开的工作台会复用服务。

```powershell
mklink-remote help
mklink-remote ping
mklink-remote list_ports
mklink-remote list_ble
mklink-remote call connect_serial --params-file connect.json
mklink-remote call rpc --params-file status.json
```

connect.json 为 `{"port":"实际串口"}`；status.json 为 `{"method":"get_status","params":{}}`。
参数文件是 UTF-8 JSON，也可用 `--params-file -` 从 stdin 读取。命令行只放文件名，不放密码、管理密钥、租约令牌。输出 `{ok,data}` 或 `{ok:false,error}`，失败退出码非零。写入超时不能重发，先查询任务和设备状态。

## 功能对应

| 工作台功能 | CLI 命令 |
|---|---|
| 串口／BLE 发现 | list_ports / list_ble |
| USB、LAN、BLE 配置连接 | connect_serial / connect_lan / connect_ble / disconnect |
| 节点状态、配置、配对、Wi-Fi 扫描 | rpc：get_status / get_config / pair / scan_wifi |
| AP、STA、AP+STA、热点名称密码、中心参数 | rpc：set_config / apply_network / connect_wifi；保留 expected_revision、change_id 与 lease_token |
| 操作权 | rpc：control.acquire / control.renew / control.release |
| 诊断筛选、查询、导出 | diagnostics_query / diagnostics_export；level=all/info/warning/error，search；导出 format=txt/json，directory 可选 |
| 原始兼容日志 | get_logs / export_logs |
| 导出默认固件 | export_firmware；directory 为不存在的输出目录 |
| 备份并安装默认固件 | start_install；install_job 查询终态 |
| 检查／暂存 S3 OTA | inspect_node_firmware / start_node_update；install_job 查询任务 |
| OTA 状态、认领、激活、确认、放弃 | rpc：firmware.status / claim / activate / confirm / abort；传 job_id、摘要、操作权等原协议字段 |
| 独立目标识别、读写、准备、烧录、校验、性能与采集 | start_target / target_job / stop_target；help 返回 action 目录 |
| 共享调试连接、状态、普通能力 | shared_control：attach / status / call / detach |
| 共享后台烧录任务 | shared_control：job.start / job.status；提交前保存 request_id，显式 confirm=true |
| 打开现有调试界面 | shared_browser 返回私有本机 URL；GUI 按钮负责打开浏览器 |
| 文件／工程选择 | CLI 直接传绝对路径；choose_target_path 校验并返回规范路径 |

service_status 返回当前管理连接和共享客户端状态；CLI 改变连接后，工作台会同步连接状态并读取当前节点配置。

外观与导航也可通过 preferences_get / preferences_set 控制：theme=dark/light，skin=technical/aurora/sand，page=overview/shared/network/gateway/logs/update/install/help。已打开的工作台会同步这些偏好。service_stop 在本服务没有在途任务、且已退出共享客户端时正常停止服务；它不强杀共享后台。

## 原版技能与 MCP

1. 用 USB1 配对，或读取先前保存的节点管理密钥。
2. `shared_control` 的 attach 参数包含 node（node_id、transport、address、token）、project_root 和可选 axf。
3. Remote 注册一个标准 Site Agent 站点。读取返回的 site 与 instance_id。
4. 启动原版安装目录的 `python -m mklink.remote.mcp`，使用原版技能的远程流程；remote_sites → remote_connect → remote_capabilities → remote_call。
5. 如果原版 MCP 在站点注册前已启动，或站点端口已变化，需要重新加载 MCP。原版站点列表不会动态重载；Remote 不修改它。

默认入口是带独立令牌的本机 WS。WSS 需要另行配置 TLS；S3 HTTP 地址不是技能站点地址。站点注册属于用户配置，不改变技能或 MCP 代码。原版技能运行时与 Remote 私有服务运行时分别维护。

无线烧录耗时可能超过原版客户端固定超时。因此 Remote 服务端为此类操作立即返回现有后台任务的 job_id、request_id 和 state；这些字段只表示已提交，不能当作烧录成功。继续使用原版 `remote_call` 的 `jobs.status` 查询终态，或用 Remote CLI 的 job.status。断开客户端不取消在途烧录，未知结果不得重放。

## 会话与日志边界

CLI 与工作台控制相同本机服务。原版 MCP 有独立远程客户端身份，共享设备、目标状态、采集缓存和任务。先在图形界面启动采集，再让 AI 订阅，可避免 AI 退出时清理其自行创建的采集。复位、烧录和显式停流影响所有观察者。

日志缓存上限为 5000 条和 8 MiB（以先达到者为准），返回 dropped 表示已移出缓存的数量。Info 表示正常事件，Warning 表示警告，Error 表示失败；未知级别的设备文本按 Info 保留。管理凭据在进入诊断缓存前脱敏。复制使用当前显示的筛选结果；CLI 导出和 GUI 导出均按传入的级别与关键词筛选。

```powershell
mklink-remote call diagnostics_query --params-file errors.json
mklink-remote call diagnostics_export --params-file export.json
```

errors.json：`{"level":"error","search":"BLE"}`。
export.json：`{"level":"warning","search":"","format":"txt","directory":"D:/Diagnostics"}`。

本机服务端点凭据存放在当前用户专属目录，禁止提交到版本库或向外公开。CLI 不自动操作本机 Wi-Fi；AP 调试应使用独立网络接口或测试代理。
