export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-4 py-16">
      <h1 className="text-4xl font-semibold tracking-tight">VAPAS</h1>
      <p className="text-lg">
        Upload your bank statement. VAPAS finds failed transactions the bank reversed late and shows the compensation
        the RBI rules say the bank owes you, with the exact rule.
      </p>
      <ul className="list-disc space-y-1 pl-5">
        <li>We never connect to your bank and never touch your money.</li>
        <li>You review and send every complaint yourself.</li>
        <li>This is not legal advice.</li>
      </ul>
      <p className="text-sm opacity-70">Under construction.</p>
    </main>
  );
}
