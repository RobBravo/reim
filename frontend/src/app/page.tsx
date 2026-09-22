import Link from "next/link";

export default function Home() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6">
      <div className="mb-10 text-center">
        <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl text-reim-text">
          Inteligencia Económica Regional
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-base text-reim-muted">
          Datos macroeconómicos oficiales para Nicaragua, Guatemala, El Salvador, Honduras, Costa Rica, Panamá y Belice.
        </p>
      </div>

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <Link
          href="/map/"
          className="group rounded-xl border border-reim-border bg-reim-surface p-6 transition-all hover:border-reim-gold/50"
        >
          <div className="text-xs font-semibold uppercase tracking-wider text-reim-gold">Explorador Espacial</div>
          <h2 className="mt-2 text-xl font-bold text-reim-text group-hover:text-reim-gold">Mapa Regional &rarr;</h2>
          <p className="mt-2 text-sm text-reim-muted">
            Visualización coroplética de indicadores nacionales y departamentales/provinciales.
          </p>
        </Link>
        <Link
          href="/series/"
          className="group rounded-xl border border-reim-border bg-reim-surface p-6 transition-all hover:border-reim-gold/50"
        >
          <div className="text-xs font-semibold uppercase tracking-wider text-reim-gold">Series de Tiempo</div>
          <h2 className="mt-2 text-xl font-bold text-reim-text group-hover:text-reim-gold">Gráficos Comparativos &rarr;</h2>
          <p className="mt-2 text-sm text-reim-muted">
            Evolución histórica y comparación multi-país con rigor de comparabilidad.
          </p>
        </Link>
        <Link
          href="/catalog/"
          className="group rounded-xl border border-reim-border bg-reim-surface p-6 transition-all hover:border-reim-gold/50"
        >
          <div className="text-xs font-semibold uppercase tracking-wider text-reim-gold">Metadatos & Licencias</div>
          <h2 className="mt-2 text-xl font-bold text-reim-text group-hover:text-reim-gold">Catálogo de Fuentes &rarr;</h2>
          <p className="mt-2 text-sm text-reim-muted">
            Transparencia total de fuentes oficiales, cadencias de actualización y licencias.
          </p>
        </Link>
      </div>
    </div>
  );
}
