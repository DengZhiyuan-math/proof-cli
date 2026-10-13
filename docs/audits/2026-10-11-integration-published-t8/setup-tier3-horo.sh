#!/bin/sh
# Trial #132, tier 3, third run: the researcher's own draft on effective equidistribution of horocycle orbits on
# X = Γ\(SL2(R)×SL2(Q_p)) (library-horo/main.tex). Unlike Connetome's note, the draft is unfinished: its main theorem
# has no statement, the height lemma has no proof, and several steps say a lemma is missing. The statements below are
# mine, written for the trial and to be checked by the researcher before the agents start:
#   - Γ is fixed as SL2(Z[1/p]) (the draft's commented example), so the height and the fibres are explicit;
#   - the height is sup Im(γ g·i): the draft's sup 1/Im(γz) is infinite for every point;
#   - MAIN (i) is modelled on Strömbergsson 2013 Theorem 1 (imported as STROM), MAIN (ii) is the p-adic L^2 gain.
# Usage: setup-tier3-horo.sh <project-folder> <library-folder holding the draft>
# Needs `proof` with Definitions: PROOF="python3 -m proof_cli.cli" and PYTHONPATH on the trial code (run-tier3-horo.sh).
set -e
ROOT="${1:?project folder}"
LIB="${2:?library folder}"
PROOF="${PROOF:-proof}"
mkdir -p "$ROOT"
# its own repository: the decisions are committed here, not into a repository the folder happens to sit in (audit A8)
git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null | grep -qx "$(cd "$ROOT" && pwd -P)" || git init -q --template= "$ROOT"
$PROOF init --root "$ROOT"
cat > "$ROOT/proof.toml" <<TOML
[studio]
budget_turns = 60
budget_minutes = 120
parallel = 2
library = ["$LIB"]                       # the draft itself, read-only for the agent
claude_config_dir = "~/.claude-Zeqome"   # the Claude Code profile every agent turn logs in with (proof-agents #8)
TOML
def() { $PROOF definition add --root "$ROOT" "$@" >/dev/null; }
node() { $PROOF node create --root "$ROOT" "$@" >/dev/null; }
ref() { $PROOF reference import --root "$ROOT" "$@" >/dev/null; }

# -- definitions (draft §1, §2, §3) ------------------------------------------------------------------------------------
def sadic-space --term "The S-adic space X" 'Fix a prime $p$. $G_\infty=SL_2(\mathbb R)$, $G_p=SL_2(\mathbb Q_p)$, $G=G_\infty\times G_p$, and $\Gamma=SL_2(\mathbb Z[1/p])$ embedded diagonally, $\gamma\mapsto(\gamma,\gamma)$; it is a non-cocompact lattice in $G$. $X=\Gamma\backslash G$, on which $G$ acts on the right: $\Gamma(g_\infty,g_p)\cdot(u,v)=\Gamma(g_\infty u,g_pv)$. $\bar\mu$ is the $G$-invariant probability measure on $X$; $L^2(X)=L^2(X,\bar\mu)$, $L^2_0(X)$ its functions of integral $0$, and $\pi$ the right-regular representation, $(\pi(g)f)(x)=f(x\cdot g)$. $|\cdot|_p$ is the $p$-adic absolute value with $|p|_p=1/p$, and $K_p=SL_2(\mathbb Z_p)$. For $t\in\mathbb R$, $t_p\in\mathbb Q_p$, $y>0$ and $j\in\mathbb Z$: $h_\infty(t)=\begin{pmatrix}1&t\\0&1\end{pmatrix}$, $h_p(t_p)=\begin{pmatrix}1&t_p\\0&1\end{pmatrix}$, $a(y)=\begin{pmatrix}y^{1/2}&0\\0&y^{-1/2}\end{pmatrix}$ (the draft writes $a_\infty(\log y)$), $a_j=\begin{pmatrix}p^j&0\\0&p^{-j}\end{pmatrix}$. An element $g$ of one factor acts as $(g,1)$ or $(1,g)$.'
def level --term "Level-n functions and Sobolev norms" 'For $n\ge1$, $W_n=\{k\in K_p: k\equiv I \bmod p^n\}$ and $\Gamma(p^n)=\{\gamma\in SL_2(\mathbb Z):\gamma\equiv I\bmod p^n\}$. A function $f$ on $X$ is of level $n$ if $f(x\cdot w)=f(x)$ for all $x\in X$, $w\in W_n$; it is smooth if $g\mapsto f(x\cdot g)$ is $C^\infty$ on $G_\infty$ for every $x$. With the basis $H=\begin{pmatrix}1&0\\0&-1\end{pmatrix}$, $X_+=\begin{pmatrix}0&1\\0&0\end{pmatrix}$, $X_-=\begin{pmatrix}0&0\\1&0\end{pmatrix}$ of the Lie algebra of $G_\infty$, each $D$ in it acts by $(Df)(x)=\frac{d}{dt}f(x\cdot\exp(tD))\big|_{t=0}$, and $\|f\|_{W_k}^2=\sum\|D_1\cdots D_jf\|_{L^2(X)}^2$, the sum over all $0\le j\le k$ and $D_1,\dots,D_j\in\{H,X_+,X_-\}$. The same formula defines $\|\cdot\|_{W_k}$ on $\Gamma_0\backslash SL_2(\mathbb R)$ for a lattice $\Gamma_0$, with its invariant probability measure.'
def height --term "Height" '$SL_2(\mathbb R)$ acts on the upper half plane $\mathbb H$ by Möbius transformations. For $x=\Gamma(g_\infty,g_p)\in X$, $\mathrm{ht}(x)=\sup\{\operatorname{Im}(\gamma g_\infty\cdot i):\gamma\in\Gamma,\ \gamma g_p\in K_p\}$; it does not depend on the representative $(g_\infty,g_p)$.'
def averages --term "Horocycle averages" '$\nu_p$ is the Haar measure on $\mathbb Q_p$ with $\nu_p(\mathbb Z_p)=1$. For $T>0$, an integer $m\ge0$ and $f$ on $X$ for which the integrals converge: $A_{T,m}f(x)=\frac{1}{Tp^m}\int_{|t_p|_p\le p^m}\int_0^Tf\big(x\cdot(h_\infty(t),h_p(t_p))\big)\,dt\,d\nu_p(t_p)$, the average over a piece of an orbit of $H_\infty\times H_p$; and $P_mf(x)=p^{-m}\int_{|t_p|_p\le p^m}f\big(x\cdot h_p(t_p)\big)\,d\nu_p(t_p)$, its $p$-adic part alone, also as an operator on $L^2(X)$.'
def spectral --term "Spectral parameter of level n" 'For $n\ge1$, let $\lambda_1(n)$ be the least eigenvalue in $(0,1/4)$ of the Laplacian $-y^2(\partial_x^2+\partial_y^2)$ on $L^2(\Gamma(p^n)\backslash\mathbb H)$. Then $s_n=\tfrac12+\sqrt{1/4-\lambda_1(n)}$, and $s_n=\tfrac12$ when there is no eigenvalue in $(0,1/4)$.'
def harish-chandra --term "Harish-Chandra function of SL2(Q_p)" 'Every $g\in G_p$ lies in $K_pa_jK_p$ for exactly one integer $j\ge0$ (Cartan decomposition), and $\Xi_p(g)=p^{-j}\,\frac{(2j+1)(p-1)+2}{p+1}$. This is the Harish-Chandra function of $G_p$ (Figà-Talamanca and Nebbia); the draft states it as Theorem "Harish-Chandra".'

# -- imported results: the literature the draft calls on ---------------------------------------------------------------
ref strombergsson2013 "On the deviation of ergodic averages for horocycle flows" 2013 --author "Andreas Strömbergsson" \
  --source-type research_paper --bibliographic-source "Journal of Modern Dynamics 7 (2013), no. 2, 291-328"
node STROM imported_result 'Let $\Gamma_0\subset SL_2(\mathbb R)$ be a non-cocompact lattice, $\mu_0$ the invariant probability measure on $\Gamma_0\backslash SL_2(\mathbb R)$, $s_1=\tfrac12+\sqrt{1/4-\lambda_1}$ for the least eigenvalue $\lambda_1\in(0,1/4)$ of the Laplacian on $\Gamma_0\backslash\mathbb H$ ($s_1=\tfrac12$ if there is none), and $\mathcal Y_{\Gamma_0}(\Gamma_0g)=\max_j\sup_{\gamma\in\Gamma_0}\operatorname{Im}(N_j^{-1}\gamma g\cdot i)$ its invariant height, $N_j$ the scaling matrices of the cusps. For every $f\in C^4(\Gamma_0\backslash SL_2(\mathbb R))$ with $\|f\|_{W_4}<\infty$, every point $q$ and every $T\ge10$: $\big|\frac1T\int_0^Tf(q\,h_\infty(t))\,dt-\int f\,d\mu_0\big|\ll_{\Gamma_0}\|f\|_{W_4}\big(r^{-1/2}\log^3(r+2)+r^{s_1-1}\big)$, where $r=T/\mathcal Y_{\Gamma_0}(q\,a(T))$.' \
  --display-label 'Strömbergsson: effective equidistribution of horocycles' --definition sadic-space --definition level \
  --reference-id strombergsson2013 --source-locator 'Theorem 1' --source-version 'J. Mod. Dyn. 7 (2013)'
ref emmv2020 "Effective equidistribution and property (tau)" 2020 --author "M. Einsiedler, G. Margulis, A. Mohammadi, A. Venkatesh" \
  --source-type research_paper --bibliographic-source "Journal of the American Mathematical Society 33 (2020), 223-289"
node DECAY imported_result 'There is $\kappa_0\in(0,1]$, depending only on $p$, such that for every $n\ge1$, every $g\in G_p$ and all level-$n$ functions $u,v\in L^2_0(X)$: $|\langle\pi(1,g)u,v\rangle|\le[K_p:W_n]\,\|u\|_2\|v\|_2\,\Xi_p(g)^{\kappa_0}$ (property $(\tau)$ for the congruence quotients, with the decay of $K_p$-finite matrix coefficients).' \
  --display-label 'Property (τ): uniform decay of p-adic matrix coefficients' --definition sadic-space --definition level --definition harish-chandra \
  --reference-id emmv2020 --source-locator 'the uniform spectral gap and decay of matrix coefficients (as the draft cites it)' --source-version 'J. Amer. Math. Soc. 33 (2020)'
ref shimura1971 "Introduction to the Arithmetic Theory of Automorphic Functions" 1971 --author "Goro Shimura" \
  --source-type textbook --bibliographic-source "Princeton University Press, 1971"
node SURJ imported_result 'For every integer $N\ge1$, reduction modulo $N$ maps $SL_2(\mathbb Z)$ onto $SL_2(\mathbb Z/N\mathbb Z)$.' \
  --display-label 'Strong approximation for SL2(Z)' \
  --reference-id shimura1971 --source-locator 'Lemma 1.38' --source-version 'Princeton UP 1971'

# -- the results ------------------------------------------------------------------------------------------------------
node MAIN theorem 'Let $n\ge1$. (i) There is $C=C(p,n)$ such that for every smooth level-$n$ function $f$ on $X$ with $\|f\|_{W_4}<\infty$, every $x\in X$, every $T\ge10$ and every integer $m\ge0$: $\big|A_{T,m}f(x)-\int_Xf\,d\bar\mu\big|\le C\,\|f\|_{W_4}\big(r^{-1/2}\log^3(r+2)+r^{s_n-1}\big)$, where $r=T\big/\max_{|t_p|_p\le p^m}\mathrm{ht}\big(x\cdot(a(T),h_p(t_p))\big)$. (ii) Suppose $\kappa\in(0,1]$ and $c\ge1$ are such that $|\langle\pi(1,g)u,v\rangle|\le c\,\|u\|_2\|v\|_2\,\Xi_p(g)^{\kappa}$ for every $g\in G_p$ and all level-$n$ functions $u,v\in L^2_0(X)$. Then every level-$n$ $f\in L^2_0(X)$ and every integer $m\ge0$ satisfy $\|P_mf\|_2\le\sqrt{2c}\,(m+1)\,p^{-m\kappa/2}\,\|f\|_2$.' \
  --display-label 'Effective equidistribution of H∞×Hp orbits on X' \
  --definition sadic-space --definition level --definition height --definition averages --definition spectral --definition harish-chandra
node HT lemma '(i) Every $x\in X$ has a representative $(g_\infty,g_p)$ with $g_p\in K_p$, and for any such representative $\mathrm{ht}(x)=\sup_{\gamma\in SL_2(\mathbb Z)}\operatorname{Im}(\gamma g_\infty\cdot i)$; in particular $\sqrt3/2\le\mathrm{ht}(x)<\infty$. (ii) $\mathrm{ht}(x\cdot k)=\mathrm{ht}(x)$ for every $k\in K_p$. (iii) $\mathrm{ht}(x\cdot g)\le e^{d(i,\,g\cdot i)}\,\mathrm{ht}(x)$ for every $g\in G_\infty$, $d$ the hyperbolic distance on $\mathbb H$; in particular $e^{-|\log y|}\mathrm{ht}(x)\le\mathrm{ht}(x\cdot a(y))\le e^{|\log y|}\mathrm{ht}(x)$ for $y>0$.' \
  --display-label 'The height: a representative in K_p, invariance, Lipschitz along G∞' --definition sadic-space --definition height
node FIB lemma 'Let $n\ge1$. (i) $\Phi_n(\Gamma(p^n)g)=\Gamma(g,1)\cdot W_n$ is a well-defined bijection from $\Gamma(p^n)\backslash SL_2(\mathbb R)$ onto $X/W_n$, and $\Phi_n(q\,g)=\Phi_n(q)\cdot g$ for $g\in G_\infty$. (ii) Consequently $f\mapsto\tilde f$, $\tilde f(\Gamma(p^n)g)=f(\Gamma(g,1))$, is a bijection from the level-$n$ functions on $X$ onto the functions on $\Gamma(p^n)\backslash SL_2(\mathbb R)$, carrying the measure induced by $\bar\mu$ to the invariant probability measure $\mu_n$: $\int_Xf\,d\bar\mu=\int\tilde f\,d\mu_n$ for integrable $f$. It commutes with $\pi(g)$ for $g\in G_\infty$, and preserves smoothness, $\|\cdot\|_{L^2}$ and every $\|\cdot\|_{W_k}$.' \
  --display-label 'Level-n functions are functions on Γ(p^n)\SL2(R)' --definition sadic-space --definition level

# what the draft leaves open, not yet precise enough to be Claims
fog() { $PROOF fog add --root "$ROOT" "$@" >/dev/null; }
fog 'A pointwise bound decaying in both T and the p-adic radius p^m: the draft ends with ν_p(B_p)^{-1/2} d_W Ξ(a_n)^{1-s_1} in the horocycle average, combining MAIN (i) and (ii); which exponent is true, and for which starting points x?' --near MAIN
fog 'The dependence of C(p,n) in MAIN (i) on the level n: the draft has μ_p(W)^{-1/2} and d_W from the Sobolev embedding; is there a bound polynomial in [K_p:W_n]?' --near MAIN
fog 'The draft lemma ht(x) ≍ exp(d_X(x,x_0)) (label heightasypm, proof "to be done"): with d_X the max of the real and p-adic distances, elements of Γ with large p-adic norm shorten the real distance, so the comparison may hold only as ht ≍ exp(c·d_X) or for a particular metric on G_p.' --near HT
fog 'General lattices Γ in SL2(R)×SL2(Q_p) and several primes S: the draft states the problem for any lattice; here Γ = SL2(Z[1/p]) is fixed.' --near MAIN
fog 'The first proof the draft announces: the Margulis–Kleinbock thickening with the Kunze–Stein inequality on the tree (Veca), and whether it is optimal in the p-adic component.' --near MAIN
$PROOF definition list --root "$ROOT"
$PROOF node show MAIN --root "$ROOT"
