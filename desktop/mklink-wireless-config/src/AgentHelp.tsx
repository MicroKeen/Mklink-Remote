export default function AgentHelp(){
  return <div className="help-start">
    <div className="help-callout"><strong>让 Agent 操作 Mklink Remote</strong><p>工作台与命令行共用本机服务。Agent 可以配置节点、安装默认固件、管理 OTA、读取诊断、执行目标任务和接入共享调试，无需模拟鼠标操作。</p><p>先打开工作台；没有界面时运行 <code>mklink-remote serve</code>。随后打开的工作台会接入同一服务。</p></div>
    <div className="help-steps">
      <article><span>01</span><h3>发现能力与设备</h3><pre>{'mklink-remote help\nmklink-remote list_ports\nmklink-remote list_ble'}</pre><p>help 返回 JSON 命令目录、参数示例和节点 RPC 方法。所有命令输出 JSON，失败返回非零退出码。</p></article>
      <article><span>02</span><h3>通过同一服务操作</h3><pre>{'mklink-remote call connect_serial --params-file connect.json\nmklink-remote call rpc --params-file status.json'}</pre><p>connect.json：<code>{'{"port":"实际串口"}'}</code></p><p>status.json：<code>{'{"method":"get_status","params":{}}'}</code></p><p>配置、热点名称与密码、STA、中心接入均通过 rpc 的 set_config / apply_network 等既有方法操作，保留版本与操作权检查。</p></article>
      <article><span>03</span><h3>原版技能加入无线会话</h3><p>通过 shared_control 的 attach 操作接入节点，检查返回的后台实例与技能站点。原版 MKLink 远程 MCP 通过已注册站点连接；不替换技能，不修改 MCP。</p><p>原版 MCP 已启动时，新增或变更站点后需重新加载它。S3 管理密钥与远程站点令牌是两份凭据，不要混用。</p></article>
      <article><span>04</span><h3>查询任务，再决定下一步</h3><pre>{'mklink-remote install_job\nmklink-remote target_job\nmklink-remote diagnostics_query'}</pre><p>默认固件安装、节点 OTA 与目标操作启动后查询任务终态。超时可能表示结果未知；先读取状态、核对文件摘要与目标身份，不能直接重发写入。</p></article>
    </div>
    <div className="help-callout"><strong>客户端身份独立，硬件状态共享</strong><p>CLI 控制的是工作台的同一服务；原版 MKLink MCP 通过远程站点持有独立客户端身份。RTT 等缓存可供双方订阅，复位、烧录和停止采集会影响同一目标。切换无线链路前，结束该节点的全部调试会话。</p><p>AI 仅订阅已有采集时，退出只释放自己的订阅；AI 自己启动并持有的采集，结束时可能一并停止。持续共同观察时，可先在图形界面启动采集。</p></div>
    <div className="help-callout"><strong>日志诊断</strong><p>左侧“日志诊断”按 Info、Warning、Error 筛选，支持搜索、暂停刷新、复制和导出。Agent 用 diagnostics_query 查询，用 diagnostics_export 导出 TXT 或 JSON；可指定 level、search、directory。日志缓存最多保留 5000 条，密码和令牌在进入缓存前脱敏。</p></div>
    <div className="help-callout"><strong>凭据与文件</strong><p>参数用 UTF-8 JSON 文件或 <code>--params-file -</code> 从标准输入传递。不要把密钥放在命令行、版本库或日志。CLI 的文件选择使用明确路径；export_logs / export_firmware 可指定 directory。浏览器入口返回本机私有 URL，请勿公开分享。</p></div>
  </div>;
}
