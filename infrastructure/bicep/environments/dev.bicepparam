using '../main.bicep'

param env = 'dev'
param location = 'northeurope'
param databricksSku = 'premium'
param databricksNoPublicIp = false
param logDailyQuotaGb = 1
