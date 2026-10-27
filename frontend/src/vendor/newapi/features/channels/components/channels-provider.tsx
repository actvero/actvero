/* Actvero host boundary for the upstream channel create/edit flow. */
import {createContext,useContext,type ReactNode} from 'react'
import type { Channel } from '@/features/model-gateway/api'
const Context = createContext<{setOpen:(open:string|null)=>void;currentRow:Channel|null;sensitiveVisible:boolean}>({setOpen:()=>{},currentRow:null,sensitiveVisible:true})
export function NativeChannelsProvider({children,onClose,currentRow=null}:{children:ReactNode;onClose:()=>void;currentRow?:Channel|null}) {
  return <Context.Provider value={{setOpen:(open)=>{if(open===null)onClose()},currentRow,sensitiveVisible:true}}>{children}</Context.Provider>
}
export function useChannels(){return useContext(Context)}
