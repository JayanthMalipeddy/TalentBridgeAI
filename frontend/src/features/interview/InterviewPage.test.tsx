import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {InterviewPage} from './InterviewPage';

vi.mock('@elevenlabs/react', () => ({
  ConversationProvider:({children}:{children:React.ReactNode}) => <>{children}</>,
  useConversation:() => ({status:'disconnected', startSession:vi.fn(), endSession:vi.fn()}),
}));
const session = {session_id:'s1', case_id:'c1', channel:'text', mode:'recruitment', state:'awaiting_consent', consent_confirmed:false, turns:[], current_turn_id:null, deadline:null, warnings:[], question_count:5, question_number:1, voice_pending:false};
function response(data:unknown, status=200) {return Promise.resolve({ok:status<400, status, json:async()=>data} as Response);}
afterEach(() => {cleanup(); vi.unstubAllGlobals();});

describe('InterviewPage', () => {
  it('requires consent and sends a scoped token only in the header', async () => {
    const fetcher = vi.fn().mockImplementationOnce(()=>response(session)).mockImplementationOnce(()=>response({...session,state:'declined'}));
    vi.stubGlobal('fetch',fetcher);
    render(<InterviewPage sessionId="s1" candidateToken="candidate-secret"/>);
    fireEvent.click(await screen.findByText('I do not consent'));
    await screen.findByText('Consent declined or withdrawn. No interview transcript is retained by this application.');
    expect(fetcher.mock.calls[1][0]).toBe('/api/interviews/s1/consent');
    expect(fetcher.mock.calls[1][1].headers.Authorization).toBe('Bearer candidate-secret');
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({confirmed:false});
    expect(document.body.textContent).not.toContain('candidate-secret');
  });
  it('submits the current turn and a unique request ID', async () => {
    const fetcher = vi.fn().mockImplementationOnce(()=>response({...session,state:'active',consent_confirmed:true,current_turn_id:'turn-1'})).mockImplementationOnce(()=>response({...session,state:'ready_to_complete'}));
    vi.stubGlobal('fetch',fetcher);
    render(<InterviewPage sessionId="s1" candidateToken="token"/>);
    fireEvent.change(await screen.findByLabelText('Your answer'), {target:{value:'I check HTTP response codes.'}});
    fireEvent.click(screen.getByText('Submit answer'));
    await screen.findByText('Complete interview');
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({turn_id:'turn-1',text:'I check HTTP response codes.'});
    expect(JSON.parse(fetcher.mock.calls[1][1].body).request_id).toBeTruthy();
  });
  it('shows expired-link errors without a fabricated interview', async () => {
    vi.stubGlobal('fetch', vi.fn(()=>response({error:{message:'unauthorized'}},401)));
    render(<InterviewPage sessionId="s1" candidateToken="expired"/>);
    expect((await screen.findByRole('alert')).textContent).toContain('invalid or expired');
    expect(screen.queryByText('Submit answer')).toBeNull();
  });
  it('offers a text alternative before voice authorization', async () => {
    const fetcher = vi.fn().mockImplementationOnce(()=>response({...session,channel:'elevenlabs'})).mockImplementationOnce(()=>response(session));
    vi.stubGlobal('fetch',fetcher);
    render(<InterviewPage sessionId="s1" candidateToken="token"/>);
    fireEvent.click(await screen.findByText('Use text interview instead'));
    await waitFor(()=>expect(fetcher.mock.calls[1][0]).toBe('/api/interviews/s1/use-text'));
    await screen.findByText('Text interview');
  });
});
