# Digital Human Agent v0.1.32 实时 Revision 事务化回滚任务书

## 状态

已完成（2026-09-02）

## 原始问题

实时文本和音频入口在启动运行前先写入 utterance revision。若随后遇到运行容量已满、会话不可用、音频入口启动失败或其他启动异常，revision 仍会保持已接受状态，客户端使用同一 revision 重试时会被误判为 stale_revision。

## 实施方案

1. 在 `ConnectionState` 增加 revision 事务票据，记录修改前状态，并仅允许对仍属于该票据的当前 revision 执行回滚。
2. 文本最终帧在通过运行启动前置步骤前持有事务；容量不足、会话不可用或启动异常时恢复原 revision 状态。
3. 音频启动同样采用事务语义；入口启动或前置中断失败时恢复原 revision，避免同一音频分段永久锁死。
4. 增加并发/过期票据保护测试，验证新 revision 已接管时旧事务回滚不会误删新状态。
5. 将各服务版本统一提升到 v0.1.32，执行 Agent、MCP、认证网关和 Web 的测试、构建与 Compose 健康检查。

## 验收标准

1. 运行容量达到上限后，原 revision 可用同一 utterance/revision 重试；不会产生第二个运行。
2. 会话启动返回不可用后，原 revision 可重试，且不会残留 active run 或错误终态。
3. 音频入口启动失败后，同一 revision 可再次发送 `audio_start`。
4. 旧事务在更新 revision 已接管后回滚返回 false，不影响新 revision。
5. 既有实时协议、流式、音频、LLM、表现层和前端回归用例继续通过。
6. Docker Compose 五个服务保持 healthy，工作树只包含本版本功能、任务书和验证 artifacts。

## 回滚方案

保留修改前关键状态文件副本、完整差异、验证记录和可执行回滚脚本；回滚后恢复 v0.1.31 的 revision 立即提交行为。验证记录见 `tmp-docs/v0.1.32-artifacts/VERIFICATION.txt`。

