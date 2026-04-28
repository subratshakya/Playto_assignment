import { startTransition, useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const DASHBOARD_REFRESH_INTERVAL_MS = 5000;

function formatMoney(amountPaise) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format((amountPaise ?? 0) / 100);
}

function formatTimestamp(value) {
  if (!value) {
    return "-";
  }

  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function buildIdempotencyKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }

  return `playto-${Date.now()}`;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    ...options,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail ?? "Request failed.");
  }

  return { data, headers: response.headers };
}

function StatusBadge({ status }) {
  const styles = {
    pending: "bg-amber-100 text-amber-800",
    processing: "bg-sky-100 text-sky-800",
    completed: "bg-emerald-100 text-emerald-800",
    failed: "bg-rose-100 text-rose-800",
  };

  return (
    <span
      className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${
        styles[status] ?? "bg-stone-200 text-stone-700"
      }`}
    >
      {status}
    </span>
  );
}

function App() {
  const [merchants, setMerchants] = useState([]);
  const [selectedMerchantId, setSelectedMerchantId] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [amountPaise, setAmountPaise] = useState("");
  const [bankAccountId, setBankAccountId] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(buildIdempotencyKey());
  const [loadingMerchants, setLoadingMerchants] = useState(true);
  const [loadingDashboard, setLoadingDashboard] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  useEffect(() => {
    let isMounted = true;

    async function loadMerchants() {
      setLoadingMerchants(true);
      setError("");
      try {
        const { data } = await apiRequest("/api/v1/merchants");
        if (!isMounted) {
          return;
        }

        setMerchants(data);
        if (data.length > 0) {
          startTransition(() => {
            setSelectedMerchantId((currentValue) => currentValue ?? data[0].id);
          });
        }
      } catch (requestError) {
        if (isMounted) {
          setError(requestError.message);
        }
      } finally {
        if (isMounted) {
          setLoadingMerchants(false);
        }
      }
    }

    loadMerchants();
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedMerchantId) {
      return undefined;
    }

    let isMounted = true;

    async function loadDashboard() {
      setLoadingDashboard(true);
      setError("");
      try {
        const { data } = await apiRequest(`/api/v1/merchants/${selectedMerchantId}/dashboard`);
        if (!isMounted) {
          return;
        }

        setDashboard(data);
        if (!bankAccountId && data.merchant.bank_accounts.length > 0) {
          setBankAccountId(String(data.merchant.bank_accounts[0].id));
        }
      } catch (requestError) {
        if (isMounted) {
          setError(requestError.message);
        }
      } finally {
        if (isMounted) {
          setLoadingDashboard(false);
        }
      }
    }

    loadDashboard();
    return () => {
      isMounted = false;
    };
  }, [selectedMerchantId]);

  const selectedMerchant =
    merchants.find((merchant) => merchant.id === selectedMerchantId) ?? null;

  async function refreshCurrentMerchant() {
    if (!selectedMerchantId) {
      return;
    }

    const [{ data: merchantList }, { data: merchantDashboard }] = await Promise.all([
      apiRequest("/api/v1/merchants"),
      apiRequest(`/api/v1/merchants/${selectedMerchantId}/dashboard`),
    ]);
    setMerchants(merchantList);
    setDashboard(merchantDashboard);
  }

  useEffect(() => {
    if (!selectedMerchantId) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      refreshCurrentMerchant().catch(() => {
        // Keep the current UI stable if a background poll fails.
      });
    }, DASHBOARD_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [selectedMerchantId]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!selectedMerchantId) {
      return;
    }

    setSubmitting(true);
    setError("");
    setSuccessMessage("");

    try {
      const { data, headers } = await apiRequest("/api/v1/payouts", {
        method: "POST",
        headers: {
          "X-Merchant-Id": String(selectedMerchantId),
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({
          amount_paise: Number(amountPaise),
          bank_account_id: Number(bankAccountId),
        }),
      });

      await refreshCurrentMerchant();
      const wasReplay = headers.get("Idempotent-Replay") === "true";
      setSuccessMessage(
        wasReplay
          ? `Replayed payout ${data.external_reference}.`
          : `Queued payout ${data.external_reference} in ${data.status} state.`,
      );
      setAmountPaise("");
      setIdempotencyKey(buildIdempotencyKey());
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen px-4 py-8 text-ink sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="glass-panel overflow-hidden rounded-4xl border border-white/70 shadow-card">
          <div className="grid gap-6 px-6 py-8 lg:grid-cols-[1.2fr_0.8fr] lg:px-10">
            <div>
              <p className="mb-3 inline-flex rounded-full border border-accent/20 bg-accent/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-accent">
                Ledger-backed payouts
              </p>
              <h1 className="font-display text-4xl leading-tight text-ink sm:text-5xl">
                Merchant balances, payout holds, and retries in one place.
              </h1>
              <p className="mt-4 max-w-2xl text-base leading-7 text-ink/70">
                The dashboard reads directly from the ledger-backed API, so every debit, refund,
                and payout state change is reflected in the merchant balance without float math.
              </p>
            </div>
            <div className="rounded-3xl bg-pine p-6 text-mist">
              <p className="text-sm uppercase tracking-[0.2em] text-mist/70">Selected merchant</p>
              <h2 className="mt-3 font-display text-3xl">
                {selectedMerchant?.name ?? "Choose a merchant"}
              </h2>
              <p className="mt-2 text-sm text-mist/70">
                {selectedMerchant
                  ? selectedMerchant.reference
                  : "Seed merchants appear here after backend setup."}
              </p>
              <div className="mt-8 grid gap-4 sm:grid-cols-3">
                <div className="rounded-2xl bg-white/10 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-mist/60">Available</p>
                  <p className="mt-2 text-xl font-semibold">
                    {formatMoney(selectedMerchant?.available_balance_paise)}
                  </p>
                </div>
                <div className="rounded-2xl bg-white/10 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-mist/60">Held</p>
                  <p className="mt-2 text-xl font-semibold">
                    {formatMoney(selectedMerchant?.held_balance_paise)}
                  </p>
                </div>
                <div className="rounded-2xl bg-white/10 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-mist/60">Ledger balance</p>
                  <p className="mt-2 text-xl font-semibold">
                    {formatMoney(selectedMerchant?.balance_paise)}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {error ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        {successMessage ? (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {successMessage}
          </div>
        ) : null}

        <section className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="glass-panel rounded-4xl border border-white/70 p-5 shadow-card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-display text-2xl">Merchants</h2>
              <span className="text-sm text-ink/50">
                {loadingMerchants ? "Loading" : merchants.length}
              </span>
            </div>
            <div className="space-y-3">
              {merchants.map((merchant) => {
                const active = merchant.id === selectedMerchantId;
                return (
                  <button
                    key={merchant.id}
                    type="button"
                    onClick={() => {
                      setBankAccountId("");
                      startTransition(() => setSelectedMerchantId(merchant.id));
                    }}
                    className={`w-full rounded-3xl border px-4 py-4 text-left transition ${
                      active
                        ? "border-pine bg-pine text-mist shadow-lg"
                        : "border-line bg-white/70 text-ink hover:border-accent hover:bg-white"
                    }`}
                  >
                    <p className="font-semibold">{merchant.name}</p>
                    <p className={`mt-1 text-sm ${active ? "text-mist/70" : "text-ink/55"}`}>
                      {merchant.reference}
                    </p>
                    <p className="mt-4 text-lg font-semibold">
                      {formatMoney(merchant.available_balance_paise)}
                    </p>
                  </button>
                );
              })}
            </div>
          </aside>

          <div className="grid gap-6">
            <section className="glass-panel rounded-4xl border border-white/70 p-6 shadow-card">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <p className="text-sm uppercase tracking-[0.18em] text-ink/50">Payout request</p>
                  <h2 className="mt-2 font-display text-3xl">Hold funds immediately</h2>
                </div>
                <p className="max-w-lg text-sm leading-6 text-ink/60">
                  Payout creation debits the ledger up front. If the processor later fails or
                  exhausts retries, the engine records a matching refund credit atomically.
                </p>
              </div>

              <form className="mt-6 grid gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-ink/70">Amount (paise)</span>
                  <input
                    className="rounded-2xl border border-line bg-white px-4 py-3 text-base outline-none transition focus:border-accent"
                    value={amountPaise}
                    onChange={(event) => setAmountPaise(event.target.value)}
                    placeholder="250000"
                    inputMode="numeric"
                    required
                  />
                </label>

                <label className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-ink/70">Bank account</span>
                  <select
                    className="rounded-2xl border border-line bg-white px-4 py-3 text-base outline-none transition focus:border-accent"
                    value={bankAccountId}
                    onChange={(event) => setBankAccountId(event.target.value)}
                    required
                  >
                    <option value="">Select an account</option>
                    {dashboard?.merchant.bank_accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.label} **** {account.account_number_last4}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="md:col-span-2 flex flex-col gap-2">
                  <span className="text-sm font-medium text-ink/70">Idempotency key</span>
                  <div className="flex flex-col gap-3 md:flex-row">
                    <input
                      className="flex-1 rounded-2xl border border-line bg-white px-4 py-3 text-base outline-none transition focus:border-accent"
                      value={idempotencyKey}
                      onChange={(event) => setIdempotencyKey(event.target.value)}
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setIdempotencyKey(buildIdempotencyKey())}
                      className="rounded-2xl border border-pine/20 px-4 py-3 text-sm font-semibold text-pine transition hover:border-pine hover:bg-pine/5"
                    >
                      Generate new key
                    </button>
                  </div>
                </label>

                <div className="md:col-span-2 flex items-center justify-between gap-4">
                  <p className="text-sm text-ink/55">
                    Reusing the same key for the same merchant returns the original API snapshot
                    for 24 hours.
                  </p>
                  <button
                    type="submit"
                    disabled={submitting || loadingDashboard}
                    className="rounded-full bg-accent px-6 py-3 text-sm font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-[#bf5330] disabled:cursor-not-allowed disabled:bg-accent/50"
                  >
                    {submitting ? "Submitting..." : "Request payout"}
                  </button>
                </div>
              </form>
            </section>

            <section className="grid gap-6 xl:grid-cols-2">
              <div className="glass-panel overflow-hidden rounded-4xl border border-white/70 shadow-card">
                <div className="flex items-center justify-between border-b border-line px-6 py-5">
                  <div>
                    <p className="text-sm uppercase tracking-[0.18em] text-ink/50">Payout history</p>
                    <h2 className="mt-2 font-display text-2xl">Latest payouts</h2>
                  </div>
                  <span className="text-sm text-ink/50">
                    {loadingDashboard
                      ? "Refreshing"
                      : `Auto-refresh 5s | ${dashboard?.payouts.length ?? 0}`}
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full">
                    <thead className="bg-white/60">
                      <tr>
                        <th className="table-cell text-left font-semibold text-ink">Reference</th>
                        <th className="table-cell text-left font-semibold text-ink">Amount</th>
                        <th className="table-cell text-left font-semibold text-ink">Status</th>
                        <th className="table-cell text-left font-semibold text-ink">Attempts</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboard?.payouts.map((payout) => (
                        <tr key={payout.id} className="border-t border-line/70">
                          <td className="table-cell">
                            <div className="max-w-[180px] truncate font-medium">
                              {payout.external_reference}
                            </div>
                            <div className="mt-1 text-xs text-ink/50">
                              {formatTimestamp(payout.created_at)}
                            </div>
                          </td>
                          <td className="table-cell font-medium">
                            {formatMoney(payout.amount_paise)}
                          </td>
                          <td className="table-cell">
                            <StatusBadge status={payout.status} />
                          </td>
                          <td className="table-cell">{payout.attempts}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="glass-panel overflow-hidden rounded-4xl border border-white/70 shadow-card">
                <div className="flex items-center justify-between border-b border-line px-6 py-5">
                  <div>
                    <p className="text-sm uppercase tracking-[0.18em] text-ink/50">Ledger entries</p>
                    <h2 className="mt-2 font-display text-2xl">Credits and debits</h2>
                  </div>
                  <span className="text-sm text-ink/50">
                    {loadingDashboard ? "Refreshing" : dashboard?.transactions.length ?? 0}
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="min-w-full">
                    <thead className="bg-white/60">
                      <tr>
                        <th className="table-cell text-left font-semibold text-ink">Type</th>
                        <th className="table-cell text-left font-semibold text-ink">Category</th>
                        <th className="table-cell text-left font-semibold text-ink">Amount</th>
                        <th className="table-cell text-left font-semibold text-ink">Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboard?.transactions.map((transaction) => (
                        <tr key={transaction.id} className="border-t border-line/70">
                          <td className="table-cell">
                            <span
                              className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${
                                transaction.direction === "credit"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : "bg-stone-200 text-stone-700"
                              }`}
                            >
                              {transaction.direction}
                            </span>
                          </td>
                          <td className="table-cell">{transaction.category}</td>
                          <td className="table-cell font-medium">
                            {formatMoney(transaction.amount_paise)}
                          </td>
                          <td className="table-cell">
                            {formatTimestamp(transaction.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}

export default App;
