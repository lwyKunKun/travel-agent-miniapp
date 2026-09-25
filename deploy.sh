#!/bin/bash
# ================================================
# 旅行小程序后端 · 部署脚本（备份 .env/数据 → 拉代码 → 重建容器 → 健康检查）
# 用法: bash deploy.sh [服务器别名，默认 aliyun-stock]
# 说明: 服务器端目录 ~/travel-agent-miniapp, 后端跑在 Docker (宿主机端口 8001)
# ================================================
set -e

# 始终切到脚本所在仓库目录, 避免在其他目录执行时 git 操作到错误仓库
cd "$(dirname "$0")"

SERVER="${1:-aliyun-stock}"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  旅行小程序后端 · 部署到 ${SERVER}${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# ---- 1. 推送本地代码到 GitHub ----
echo -e "${YELLOW}[1/4] 推送代码到 GitHub...${NC}"
git add -A
if git diff --cached --quiet; then
    echo "  没有需要提交的改动"
else
    git commit -m "部署: ${TIMESTAMP}"
fi
git push origin main
echo -e "${GREEN}  GitHub 推送完成${NC}"
echo ""

# ---- 2. 服务器备份 (仅 .env 与 data 数据卷; 代码由 git 管理无需备份) ----
echo -e "${YELLOW}[2/4] 备份服务器 .env 与数据...${NC}"
ssh "${SERVER}" "
    BACKUP_DIR=~/travel-miniapp-backups/${TIMESTAMP}
    mkdir -p \${BACKUP_DIR}
    cd ~/travel-agent-miniapp/backend
    FAIL=0
    cp .env \${BACKUP_DIR}/ 2>/dev/null || { echo '  ❌ .env 备份失败'; FAIL=1; }
    cp docker-compose.override.yml \${BACKUP_DIR}/ 2>/dev/null || echo '  ⚠️ docker-compose.override.yml 不存在, 跳过'
    cp -r data \${BACKUP_DIR}/data 2>/dev/null || { echo '  ❌ data/ 备份失败'; FAIL=1; }
    if [ \$FAIL -eq 1 ]; then echo '  备份不完整, 中止部署'; exit 1; fi
    echo '  备份完成: '\${BACKUP_DIR}
"
echo ""

# ---- 3. 拉取最新代码并重建容器 ----
# chown 1000:1000: 容器内以非 root 用户 appuser(uid=1000) 运行,
# 宿主机 data/logs 目录若为 root 属主, 容器内写 SQLite 会报 unable to open database file
echo -e "${YELLOW}[3/4] 服务器拉取代码 + 重建容器...${NC}"
ssh "${SERVER}" "
    cd ~/travel-agent-miniapp && \
    git fetch origin && \
    git reset --hard origin/main && \
    cd backend && \
    mkdir -p data logs && \
    chown -R 1000:1000 data logs && \
    docker compose up -d --build 2>&1 | tail -5 && \
    docker image prune -f >/dev/null
"
echo -e "${GREEN}  容器重建完成${NC}"
echo ""

# ---- 4. 健康检查 ----
echo -e "${YELLOW}[4/4] 健康检查...${NC}"
sleep 5
HEALTH=$(ssh "${SERVER}" "curl -s -m 10 http://localhost:8001/health || echo FAIL")
if echo "${HEALTH}" | grep -q '"healthy"'; then
    echo -e "${GREEN}  ✅ 服务健康: ${HEALTH}${NC}"
else
    echo -e "${RED}  ❌ 健康检查失败: ${HEALTH}${NC}"
    echo -e "${RED}  查看日志: ssh ${SERVER} 'docker logs --tail 50 trip-planner-backend'${NC}"
    exit 1
fi
echo ""
echo -e "${GREEN}🎉 部署完成: http://<服务器IP>:8001${NC}"
