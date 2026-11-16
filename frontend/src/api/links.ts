import {request} from './client';import {LinkState} from '../types/domain';
export const getLinks=(studyId:number)=>request<LinkState>(`/studies/${studyId}/links`);
export const addLink=(studyId:number,window_a_id:number,window_b_id:number)=>request<{id:number}>(`/studies/${studyId}/links`,{method:'POST',body:JSON.stringify({study_id:studyId,window_a_id,window_b_id})});
export const revokeLink=(studyId:number,id:number)=>request<{id:number}>(`/studies/${studyId}/links/${id}`,{method:'DELETE'});
