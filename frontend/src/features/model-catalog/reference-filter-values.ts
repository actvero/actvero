export type ReferenceFilters = {
  provider: string
  developer: string
  tools: string
  reasoning: string
  structured_output: string
  input_modality: string
  output_modality: string
  min_context: string
  price: string
  status: string
  sort: string
}
export const emptyReferenceFilters: ReferenceFilters = {
  provider: '',
  developer: '',
  tools: '',
  reasoning: '',
  structured_output: '',
  input_modality: '',
  output_modality: '',
  min_context: '',
  price: 'all',
  status: 'all',
  sort: 'relevance',
}
