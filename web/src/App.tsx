import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Accounts from './pages/Accounts'
import Alerts from './pages/Alerts'
import Assistant from './pages/Assistant'
import Budget from './pages/Budget'
import Fees from './pages/Fees'
import Findings from './pages/Findings'
import Goals from './pages/Goals'
import Household from './pages/Household'
import Insights from './pages/Insights'
import CashFlow from './pages/CashFlow'
import Dashboard from './pages/Dashboard'
import NetWorth from './pages/NetWorth'
import PlanPage from './pages/Plan'
import Funds from './pages/Funds'
import Investments from './pages/Investments'
import Receipts from './pages/Receipts'
import Review from './pages/Review'
import OAuthReturn from './pages/OAuthReturn'
import Recurring from './pages/Recurring'
import RulesPage from './pages/Rules'
import Search from './pages/Search'
import Settings from './pages/Settings'
import Shared from './pages/Shared'
import Spending from './pages/Spending'
import Subscriptions from './pages/Subscriptions'
import Transactions from './pages/Transactions'
import Trends from './pages/Trends'
import Welcome from './pages/Welcome'

export default function App() {
  return (
    <Routes>
      {/* A share link is opened by somebody outside the household. It gets no
          sidebar, no navigation and no way into the rest of the app. */}
      <Route path="/shared/:token" element={<Shared />} />
      <Route
        path="*"
        element={
          <Layout>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/welcome" element={<Welcome />} />
              <Route path="/review" element={<Review />} />
              <Route path="/search" element={<Search />} />
              <Route path="/transactions" element={<Transactions />} />
              <Route path="/budget" element={<Budget />} />
              <Route path="/spending" element={<Spending />} />
              <Route path="/recurring" element={<Recurring />} />
              <Route path="/cash-flow" element={<CashFlow />} />
              <Route path="/net-worth" element={<NetWorth />} />
              <Route path="/goals" element={<Goals />} />
              <Route path="/findings" element={<Findings />} />
              <Route path="/trends" element={<Trends />} />
              <Route path="/subscriptions" element={<Subscriptions />} />
              <Route path="/plan" element={<PlanPage />} />
              <Route path="/assistant" element={<Assistant />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/fees" element={<Fees />} />
              <Route path="/insights" element={<Insights />} />
              <Route path="/funds" element={<Funds />} />
              <Route path="/investments" element={<Investments />} />
              <Route path="/receipts" element={<Receipts />} />
              <Route path="/rules" element={<RulesPage />} />
              <Route path="/household" element={<Household />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/accounts" element={<Accounts />} />
              <Route path="/connections" element={<Accounts />} />
              <Route path="/oauth" element={<OAuthReturn />} />
            </Routes>
          </Layout>
        }
      />
    </Routes>
  )
}
