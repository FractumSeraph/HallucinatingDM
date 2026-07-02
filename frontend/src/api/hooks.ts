import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'
import type { Campaign, Member, User } from './types'

export function useMe() {
  return useQuery<User | null>({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api.get<User>('/auth/me')
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post('/auth/logout'),
    onSuccess: () => qc.setQueryData(['me'], null),
  })
}

export function useCampaigns() {
  return useQuery<Campaign[]>({
    queryKey: ['campaigns'],
    queryFn: () => api.get('/campaigns'),
  })
}

export function useCampaign(id: string) {
  return useQuery<Campaign>({
    queryKey: ['campaigns', id],
    queryFn: () => api.get(`/campaigns/${id}`),
  })
}

export function useMembers(campaignId: string) {
  return useQuery<Member[]>({
    queryKey: ['campaigns', campaignId, 'members'],
    queryFn: () => api.get(`/campaigns/${campaignId}/members`),
  })
}
