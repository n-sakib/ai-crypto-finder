import { createBrowserRouter } from 'react-router-dom';
import App from './App';
import Dashboard from './pages/Dashboard';
import TokenDetail from './pages/TokenDetail';
import Pipeline from './pages/Pipeline';
import TelegramDiscovery from './pages/TelegramDiscovery';
import RedditDiscovery from './pages/RedditDiscovery';
import TwitterDiscovery from './pages/TwitterDiscovery';
import GMGNDiscovery from './pages/GMGNDiscovery';
import DexScreenerDiscovery from './pages/DexScreenerDiscovery';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'token/:id', element: <TokenDetail /> },
      { path: 'pipeline', element: <Pipeline /> },
      { path: 'telegram', element: <TelegramDiscovery /> },
      { path: 'reddit', element: <RedditDiscovery /> },
      { path: 'twitter', element: <TwitterDiscovery /> },
      { path: 'gmgn', element: <GMGNDiscovery /> },
      { path: 'dexscreener', element: <DexScreenerDiscovery /> },
    ],
  },
]);
