import pinText from '../adapter/upstream.json?raw';
const pin=JSON.parse(pinText) as {upstream_commit:string};
export default function AgentHelp(){
  return <div className="help-start">
    <div className="help-callout"><strong>让 Agent 操作 Mklink Remote</strong><p>优先使用 CLI 或共享后台。工作台与 CLI 共用本机服务，原版 MKLink MCP 通过注册站点接入；不需要模拟鼠标，也不覆盖原版技能。</p><p>本包后台绑定 <code>{pin.upstream_commit.slice(0,7)}</code>（0.4.3，含 PR #70 / #72）。运行中的服务以 <code>mklink-remote call capabilities</code> 返回为准；版本不符时，结束任务并退出会话后再重启 Remote。</p></div>
    <div className="help-steps">
      <article><span>01</span><h3>先查状态</h3><pre>{'mklink-remote help\nmklink-remote call capabilities\nmklink-remote service_status\nmklink-remote target_job'}</pre><p>先打开工作台；无界面时运行 <code>mklink-remote serve</code>。已有连接或任务时先核对归属，不另开独占连接。</p></article>
      <article><span>02</span><h3>连接并核对能力</h3><pre>{'mklink-remote call connect_lan --params-file connect.json\nmklink-remote call rpc --params-file status.json'}</pre><p>connect.json 包含 <code>url</code> 与 <code>token</code>。status.json：<code>{'{"method":"get_status","params":{}}'}</code>。也可使用 connect_serial / connect_ble，参数以 help 为准。</p><p>先核对节点、V4 状态和目标身份。SuperWatch 由后台检查实际能力及采样时基，不以固件版本号代替能力检查。</p></article>
      <article><span>03</span><h3>复用共享调试</h3><p>通过 shared_control 的 attach 接入工程，使用匹配的 AXF / ELF；核对返回的后台实例与站点，再让原版远程 MCP 连接。支持站点重载的客户端可重载配置，旧客户端需重启。</p><p>自己启动的任务要负责收尾；仅订阅他人采集时只退出自己的客户端。切换链路前先结束该节点的全部调试会话。</p></article>
      <article><span>04</span><h3>等待停止完成</h3><pre>{'mklink-remote stop_target\nmklink-remote target_job\nmklink-remote diagnostics_query'}</pre><p>stop_target 只用于本服务启动的独立目标任务。返回 accepted 只表示请求已接受，必须继续查询 target_job，直到 running=false。共享后台任务通过其自身接口停止和查询。</p><p>保持连接直到尾部收完、任务结束。失败或 outcome_unknown 时先保存诊断并核对后台、租约和队列，不能重放旧命令或强行清空数据。</p></article>
    </div>
    <details className="disclosure"><summary>采集质量与性能边界</summary><div className="panel-body"><p>同时记录请求速率、目标时间戳速率、接收速率、解析丢帧、CRC 错误、队列变化及停止结果。没有返回的统计是“未验证”，不能记作零丢帧；解析丢帧也不等于丢失样本总数。</p><p>从低负载开始，逐步提高；持续积压时降低速率或通道数据量，不自动降采样后宣称原速率通过。Wi-Fi 800 Hz 尚未稳定通过，USB Full Speed、信号和处理开销都会影响体验。STOP 后 RAM 读回须在已确认健康、无在途目标任务时执行，不因请求超时就反复重试。</p></div></details>
    <details className="disclosure"><summary>OTA、写入与凭据</summary><div className="panel-body"><p>安装与 OTA 启动后查询 install_job；备用槽写完不等于新固件已生效，还需校验镜像、激活、重连并确认版本。写入要有明确范围、已核验备份及恢复方案；结果未知时禁止重复写入。</p><p>参数用 UTF-8 JSON 文件或 <code>--params-file -</code> 传入。密钥不放命令行、截图或日志；S3 管理密钥与远程站点令牌不可混用。本机工作台 URL 也不公开分享。</p><p>日志页支持筛选和导出；Agent 使用 diagnostics_query / diagnostics_export。未经指示不更改电脑 Wi-Fi，也不更新原 MKLink 安装或板端固件。</p></div></details>
  </div>;
}
