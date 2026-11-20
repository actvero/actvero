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
  },
  "workbenches": {
    "list": {
      "method": "GET",
      "path": "/organizations/{org_id}/workbenches",
      "description": "查询组织工作台",
      "write": false,
      "arguments": [],
      "query": [
        {
          "name": "category",
          "description": "按工作台分类筛选",
          "required": false,
          "positiveInteger": false,
          "default": null
        },
        {
          "name": "status",
          "description": "draft、published 或 withdrawn",
          "required": false,
          "positiveInteger": false,
          "default": null
        },
        {
          "name": "q",
          "description": "搜索展示名称或包名",
          "required": false,
          "positiveInteger": false,
          "default": null
        },
        {
          "name": "page",
          "description": "页码",
          "required": false,
          "positiveInteger": true,
          "default": null
        }
      ],
      "body": null
    },
    "show": {
      "method": "GET",
      "path": "/organizations/{org_id}/workbenches/{workbench_id}",
      "description": "查看工作台详情和版本历史",
      "write": false,
      "arguments": [
        {
          "name": "workbench_id",
          "alias": "id"
        }
      ],
      "query": [],
      "body": null
    },
    "create": {
      "method": "POST",
      "path": "/organizations/{org_id}/workbenches",
      "description": "上传安装包并创建工作台草稿",
      "write": true,
      "arguments": [],
      "query": [],
      "body": null,
      "binary": true
    },
    "upload": {
      "method": "POST",
      "path": "/organizations/{org_id}/workbenches/{workbench_id}/versions",
      "description": "上传同一工作台的新版本草稿",
      "write": true,
      "arguments": [
        {
          "name": "workbench_id",
          "alias": "id"
        }
      ],
      "query": [
        {
          "name": "revision",
          "description": "工作台当前修订号",
          "required": true,
          "positiveInteger": true,
          "default": null
        }
      ],
      "body": null,
      "binary": true
    },
    "update": {
      "method": "PUT",
      "path": "/organizations/{org_id}/workbenches/{workbench_id}",
      "description": "更新工作台展示资料",
      "write": true,
      "arguments": [
        {
          "name": "workbench_id",
          "alias": "id"
        }
      ],
      "query": [],
      "body": "WorkbenchMetadata"
    },
    "scope": {
      "method": "PUT",
      "path": "/organizations/{org_id}/workbenches/{workbench_id}/scope",
      "description": "设置工作台使用范围",
      "write": true,
      "arguments": [
        {
          "name": "workbench_id",
          "alias": "id"
        }
      ],
      "query": [],
      "body": "WorkbenchScope"
    },
    "configure": {
      "method": "PUT",
      "path": "/organizations/{org_id}/workbenches/{workbench_id}/runtime-config",
      "description": "保存工作台运行配置",
      "write": true,
      "arguments": [
        {
          "name": "workbench_id",
          "alias": "id"
        }
      ],
      "query": [],
      "body": "WorkbenchConfigUpdate"
    },
    "publish": {
      "method": "POST",
      "path": "/organizations/{org_id}/workbenches/{workbench_id}/versions/{version_id}/publish",
      "description": "发布工作台版本",
      "write": true,
      "arguments": [
        {
          "name": "workbench_id",
          "alias": "id"
        },
        {
          "name": "version_id",
          "alias": "version-id"
        }
      ],
      "query": [],
      "body": "WorkbenchPublish"
    },
    "withdraw": {
      "method": "POST",
      "path": "/organizations/{org_id}/workbenches/{workbench_id}/versions/{version_id}/withdraw",
      "description": "下架当前工作台版本",
      "write": true,
      "arguments": [
        {
          "name": "workbench_id",
          "alias": "id"
        },
        {
          "name": "version_id",
          "alias": "version-id"
        }
      ],
      "query": [],
      "body": "WorkbenchRevision"
    },
    "delete-draft": {
      "method": "DELETE",
      "path": "/organizations/{org_id}/workbenches/{workbench_id}/versions/{version_id}",
      "description": "删除未发布的工作台版本草稿",
      "write": true,
      "arguments": [
        {
          "name": "workbench_id",
          "alias": "id"
        },
        {
          "name": "version_id",
          "alias": "version-id"
        }
      ],
      "query": [
        {
          "name": "revision",
          "description": "工作台当前修订号",
          "required": true,
          "positiveInteger": true,
          "default": null
        }
      ],
      "body": null
    }
  }
} as const;
