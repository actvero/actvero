/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  ADMIN_PERMISSION_ACTIONS,
  ADMIN_PERMISSION_RESOURCES,
  hasPermission,
} from '@newapi/lib/admin-permissions'
import { handleServerError } from '@newapi/lib/handle-server-error'
import { createServerError } from '@newapi/lib/server-error-message'
import { useAuthStore } from '@newapi/stores/auth-store'
import { invalidateModelPricing } from '@newapi/features/model-pricing/api'

import { createChannel, updateChannel, type ChannelTemplatePricing } from '../api'
import { ERROR_MESSAGES, SUCCESS_MESSAGES } from '../constants'
import {
  transformFormDataToCreatePayload,
  transformFormDataToUpdatePayload,
  type ChannelFormValues,
} from '../lib'
import type { Channel } from '../types'

type UseChannelMutateFormParams = {
  currentRow?: Pick<Channel, 'id'> | null
  isEditing: boolean
  isMultiKeyChannel: boolean
  onSuccess: () => void
}

const SENSITIVE_UPDATE_FIELDS = [
  'type',
  'key',
  'base_url',
  'openai_organization',
  'param_override',
  'header_override',
  'setting',
  'settings',
  'other',
] satisfies (keyof Channel)[]

function reportTemplatePricing(pricing?: ChannelTemplatePricing) {
  if (pricing?.pending) {
    toast.warning(
      '渠道已保存，官方价格暂未导入，请在模型定价中核对后再开放使用。'
    )
  } else if (pricing?.unavailable.length) {
    toast.warning(
      `渠道已保存，以下模型未匹配已核实的火山官方定价，请在模型定价中核对：${pricing.unavailable.join('、')}`
    )
  }
}

export function useChannelMutateForm(props: UseChannelMutateFormParams) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const currentUser = useAuthStore((s) => s.auth.user)
  const canEditSensitive = hasPermission(
    currentUser,
    ADMIN_PERMISSION_RESOURCES.CHANNEL,
    ADMIN_PERMISSION_ACTIONS.SENSITIVE_WRITE
  )

  return useMutation({
    mutationFn: async (data: ChannelFormValues): Promise<string> => {
      if (props.isEditing && props.currentRow) {
        const payload = transformFormDataToUpdatePayload(
          data,
          props.currentRow.id
        )
        if (!data.key?.trim()) {
          delete payload.key
        }
        if (!canEditSensitive) {
          for (const field of SENSITIVE_UPDATE_FIELDS) {
            delete payload[field]
          }
        }
        const payloadWithKeyMode =
          canEditSensitive &&
          props.isMultiKeyChannel &&
          data.key?.trim() &&
          data.key_mode
            ? {
                ...payload,
                key_mode: data.key_mode,
              }
            : payload

        const response = await updateChannel(props.currentRow.id, {
          ...payloadWithKeyMode,
          ...(canEditSensitive && props.isMultiKeyChannel
            ? { multi_key_mode: data.multi_key_type }
            : {}),
        })
        if (!response.success) {
          throw createServerError(response, t(ERROR_MESSAGES.UPDATE_FAILED))
        }
        reportTemplatePricing(response.pricing)
        if (response.pricing) await invalidateModelPricing(queryClient)
        return SUCCESS_MESSAGES.UPDATED
      }

      const payload = transformFormDataToCreatePayload(data)
      const response = await createChannel(payload)
      if (!response.success) {
        throw createServerError(response, t(ERROR_MESSAGES.CREATE_FAILED))
      }
      reportTemplatePricing(response.pricing)
      if (response.pricing) await invalidateModelPricing(queryClient)
      return SUCCESS_MESSAGES.CREATED
    },
    onSuccess: (messageKey) => {
      toast.success(t(messageKey))
      props.onSuccess()
    },
    onError: (error: unknown) => {
      handleServerError(error, t(ERROR_MESSAGES.CREATE_FAILED))
    },
  })
}

