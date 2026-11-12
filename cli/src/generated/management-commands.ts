// 由 OpenAPI 生成，请运行 make generate-api 更新。
export const managementCommands = {
  "experts": {
    "list": {
      "method": "GET",
      "path": "/organizations/{org_id}/experts",
      "description": "查询专家",
      "write": false,
      "arguments": [],
      "query": [
        {
          "name": "q",
          "description": "搜索词",
          "required": false,
          "positiveInteger": false,
          "default": null
        },
        {
          "name": "category",
          "description": "类别",
          "required": false,
          "positiveInteger": false,
          "default": null
        },
        {
          "name": "status",
          "description": "published 或 unpublished",
          "required": false,
          "positiveInteger": false,
          "default": null
        },
        {
          "name": "page",
          "description": "页码",
          "required": false,
          "positiveInteger": true,
          "default": 1
        }
      ],
      "body": null
    },
    "show": {
      "method": "GET",
      "path": "/organizations/{org_id}/experts/{expert_id}",
      "description": "查看专家与发布版本",
      "write": false,
      "arguments": [
        {
          "name": "expert_id",
          "alias": "id"
        }
      ],
      "query": [],
      "body": null
    },
    "update": {
      "method": "PUT",
      "path": "/organizations/{org_id}/experts/{expert_id}",
      "description": "提交 ExpertUpdate，包含当前草稿修订号 revision。",
      "write": true,
      "arguments": [
        {
          "name": "expert_id",
          "alias": "id"
        }
      ],
      "query": [],
      "body": "ExpertUpdate"
    }
  }
} as const;
