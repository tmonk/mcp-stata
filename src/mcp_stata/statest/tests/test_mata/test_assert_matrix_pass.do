* test_assert_matrix_pass.do
matrix A = (1, 2 \ 3, 4)
matrix B = (1, 2 \ 3, 4)
st_assert_matrix A, expected(B)

matrix C = (1.0001, 2 \ 3, 4)
st_assert_matrix A, expected(C) tol(0.001)
