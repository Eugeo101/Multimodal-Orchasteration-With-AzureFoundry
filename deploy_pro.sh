#!/bin/bash
# deploy.sh
# ──────────────────────────────────────────────────────────────────────────────
# One-shot deploy script for Ahmed-Agent → Azure Container Apps
#
# Prerequisites:
#   az login
#   az extension add --name containerapp
#
# Run:
#   chmod +x deploy.sh
#   ./deploy.sh
# ──────────────────────────────────────────────────────────────────────────────

set -e  # exit on any error

# ── EDIT THESE ────────────────────────────────────────────────────────────────
RESOURCE_GROUP="ahmed-agent-rg"
LOCATION="eastus"
ACR_NAME="ahmedagentacr"          # must be globally unique, lowercase, 5-50 chars
APP_NAME="ahmed-agent"
ENVIRONMENT_NAME="ahmed-agent-env"
IMAGE_TAG="latest"
# ─────────────────────────────────────────────────────────────────────────────

IMAGE_FULL="${ACR_NAME}.azurecr.io/${APP_NAME}:${IMAGE_TAG}"

echo ""
echo "════════════════════════════════════════════════"
echo "  Ahmed-Agent → Azure Container Apps Deploy"
echo "════════════════════════════════════════════════"
echo ""

# 1. Resource Group
echo "1️⃣  Creating resource group: $RESOURCE_GROUP"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

# 2. Azure Container Registry
echo "2️⃣  Creating container registry: $ACR_NAME"
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Basic \
  --admin-enabled true \
  --output none

# 3. Build + push image to ACR (no local Docker needed)
echo "3️⃣  Building and pushing image to ACR..."
az acr build \
  --registry "$ACR_NAME" \
  --image "${APP_NAME}:${IMAGE_TAG}" \
  .

# 4. Container Apps Environment
echo "4️⃣  Creating Container Apps environment: $ENVIRONMENT_NAME"
az containerapp env create \
  --name "$ENVIRONMENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

# 5. Get ACR credentials
ACR_SERVER="${ACR_NAME}.azurecr.io"
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query passwords[0].value -o tsv)

# 6. Deploy Container App
echo "5️⃣  Deploying container app: $APP_NAME"
az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT_NAME" \
  --image "$IMAGE_FULL" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_NAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 10 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --output none

# 7. Enable Managed Identity (so DefaultAzureCredential works — no client secret needed)
echo "6️⃣  Enabling managed identity..."
az containerapp identity assign \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --system-assigned \
  --output none

# 8. Get public URL
APP_URL=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

echo ""
echo "════════════════════════════════════════════════"
echo "  ✅ Deployment complete!"
echo ""
echo "  URL:    https://${APP_URL}"
echo "  Health: https://${APP_URL}/health"
echo "  Chat:   POST https://${APP_URL}/chat"
echo ""
echo "  Test it:"
echo "  curl -X POST https://${APP_URL}/chat \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"message\": \"Hello!\"}'"
echo "════════════════════════════════════════════════"
echo ""
echo "⚠️  IMPORTANT: Assign your Managed Identity access to:"
echo "   - Azure Foundry project (Contributor role)"
echo "   - Azure Storage (Storage Blob Data Contributor)"
echo ""
echo "   az role assignment create \\"
echo "     --assignee <managed-identity-principal-id> \\"
echo "     --role 'Contributor' \\"
echo "     --scope /subscriptions/<sub>/resourceGroups/$RESOURCE_GROUP"
