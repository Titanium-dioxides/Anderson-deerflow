import Mathlib

open Nat

/-- 测试用：add_zero 定理 -/
theorem add_zero (n : Nat) : n + 0 = n := by
  sorry

/-- 测试用：succ_inj -/
lemma succ_inj {a b : Nat} (h : Nat.succ a = Nat.succ b) : a = b := by
  injection h

/-- 测试用：带独立声明的 add_comm -/
theorem add_comm_test (a b : Nat) : a + b = b + a := by
  induction a with
  | zero => simp
  | succ a ih =>
    simp [add_succ, ih]
