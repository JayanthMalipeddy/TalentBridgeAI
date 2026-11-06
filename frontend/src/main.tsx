import {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Landing, Brand} from './Landing';
import {Workspace} from './Workspace';
import {InterviewPage} from './features/interview/InterviewPage';
import './style.css';

function App() {
  const [token] = useState(() => new URLSearchParams(location.hash.slice(1)).get('token') ?? '');
  useEffect(() => {if (location.hash) history.replaceState(null, '', location.pathname);}, []);
  if (location.pathname.startsWith('/interview/')) {
    return <main className="panel candidate"><Brand/><InterviewPage sessionId={location.pathname.split('/')[2] ?? ''} candidateToken={token}/></main>;
  }
  return location.pathname.startsWith('/app') ? <Workspace/> : <Landing/>;
}
createRoot(document.getElementById('root')!).render(<App/>);
