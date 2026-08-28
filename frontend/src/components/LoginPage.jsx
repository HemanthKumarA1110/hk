import { useState } from 'react'
import { fetchMe, login } from '../api'
import { useAuth } from '../context/AuthContext'
import BrandLogo from './BrandLogo'
import { APP_DESCRIPTION } from '../config/brand'
import BrokerSetupForm from './BrokerSetupForm'

export default function LoginPage() {
  const { setUser } = useAuth()

  const [mode, setMode] = useState('login')

  const [form, setForm] = useState({

    username: 'admin',

    password: 'Admin@12345',

  })

  const [error, setError] = useState('')

  const [busy, setBusy] = useState(false)



  const onChange = (event) => {

    setForm((prev) => ({ ...prev, [event.target.name]: event.target.value }))

  }



  const handleLogin = async (event) => {

    event.preventDefault()

    setBusy(true)

    setError('')

    try {

      const tokens = await login(form.username, form.password)

      localStorage.setItem('access_token', tokens.access_token)

      localStorage.setItem('refresh_token', tokens.refresh_token)

      const profile = await fetchMe()

      setUser(profile)

    } catch (err) {

      setError(err.response?.data?.detail || 'Login failed')

    } finally {

      setBusy(false)

    }

  }



  const handleBrokerSuccess = (profile) => {

    setUser(profile)

  }



  return (

    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">

      <div className="w-full max-w-5xl grid lg:grid-cols-2 gap-8">

        <section className="rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 to-slate-950 p-8 shadow-2xl">
          <BrandLogo size="lg" showTagline />
          <p className="mt-6 text-slate-400 leading-relaxed">{APP_DESCRIPTION}</p>
          <p className="mt-3 text-slate-500 text-sm leading-relaxed">
            Sign in, then connect Angel One for live trading.
          </p>

          <ul className="mt-8 space-y-3 text-sm text-slate-300">

            <li>Live MARKET orders via Angel One</li>

            <li>Encrypted broker credentials at rest</li>

            <li>Live OTP generated from your TOTP secret automatically</li>

          </ul>

        </section>



        <section className="rounded-2xl border border-slate-800 bg-slate-900/70 p-8 shadow-xl">

          <div className="flex gap-2 mb-6">

            <button

              type="button"

              onClick={() => setMode('login')}

              className={`px-4 py-2 rounded-lg text-sm font-medium ${mode === 'login' ? 'bg-emerald-500 text-slate-950' : 'bg-slate-800'}`}

            >

              Login

            </button>

            <button

              type="button"

              onClick={() => setMode('broker')}

              className={`px-4 py-2 rounded-lg text-sm font-medium ${mode === 'broker' ? 'bg-emerald-500 text-slate-950' : 'bg-slate-800'}`}

            >

              Angel One Setup

            </button>

          </div>



          {mode === 'login' ? (

            <form onSubmit={handleLogin} className="space-y-4">

              <label className="block text-sm">

                Username

                <input

                  name="username"

                  value={form.username}

                  onChange={onChange}

                  className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"

                />

              </label>

              <label className="block text-sm">

                Password

                <input

                  type="password"

                  name="password"

                  value={form.password}

                  onChange={onChange}

                  className="mt-1 w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2"

                />

              </label>

              {error && <p className="text-rose-400 text-sm">{error}</p>}

              <button

                type="submit"

                disabled={busy}

                className="w-full rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold py-2.5"

              >

                {busy ? 'Signing in...' : 'Sign In'}

              </button>

            </form>

          ) : (

            <BrokerSetupForm

              onSuccess={handleBrokerSuccess}

              showLoginFields

            />

          )}

        </section>

      </div>

    </div>

  )

}


